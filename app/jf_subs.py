"""Untertitel für das Butchies Media Center (Jellyfin-kompatibel).

- Externe Dateien neben dem Film: Film.srt, Film.de.srt, Film.ger.forced.ass, Film.German.vtt …
- Eingebettete Spuren (MKV/MP4): Text (SRT/ASS/mov_text) und Bild (PGS) werden einmal per FFmpeg
  herausgelöst und zwischengespeichert (data/subcache).
- Ausgabe in den Formaten, die Jellyfin-Clients abrufen: vtt, srt, ass, js (TrackEvents-JSON), sup (PGS).
Die Originaldateien werden nie verändert.
"""
import json
import os
import re
import subprocess
import threading
from pathlib import Path

S = None          # server-Modul
TICKS = 10_000_000
SUB_EXT = {'.srt': 'subrip', '.vtt': 'webvtt', '.ass': 'ass', '.ssa': 'ssa'}
TEXT_CODECS = {'subrip', 'srt', 'ass', 'ssa', 'webvtt', 'mov_text', 'text'}
IMAGE_OK = {'pgssub'}            # Bild-Untertitel, die jellyfin-web selbst zeichnen kann
MAX_SUB_BYTES = 8 * 1024 * 1024

LANGS = {
    'ger': ('Deutsch', ('de', 'ger', 'deu', 'german', 'deutsch')),
    'eng': ('Englisch', ('en', 'eng', 'english', 'englisch')),
    'fre': ('Französisch', ('fr', 'fre', 'fra', 'french', 'francais', 'français')),
    'spa': ('Spanisch', ('es', 'spa', 'spanish', 'espanol', 'español')),
    'ita': ('Italienisch', ('it', 'ita', 'italian', 'italiano')),
    'tur': ('Türkisch', ('tr', 'tur', 'turkish', 'türkçe', 'turkce')),
    'pol': ('Polnisch', ('pl', 'pol', 'polish', 'polski')),
    'rus': ('Russisch', ('ru', 'rus', 'russian')),
    'dut': ('Niederländisch', ('nl', 'dut', 'nld', 'dutch')),
    'por': ('Portugiesisch', ('pt', 'por', 'portuguese')),
    'jpn': ('Japanisch', ('ja', 'jpn', 'japanese')),
    'kor': ('Koreanisch', ('ko', 'kor', 'korean')),
    'chi': ('Chinesisch', ('zh', 'chi', 'zho', 'chinese')),
    'ara': ('Arabisch', ('ar', 'ara', 'arabic')),
}
_ALIAS = {a: code for code, (_, al) in LANGS.items() for a in al}
_ALIAS.update({'deu': 'ger', 'fra': 'fre', 'nld': 'dut', 'zho': 'chi'})
FORCED = {'forced', 'erzwungen', 'foreign', 'forcednarrative'}
SDH = {'sdh', 'cc', 'hi', 'hoh'}


def setup(server_module):
    global S
    S = server_module


def lang_code(v):
    v = (v or '').strip().lower()
    return _ALIAS.get(v, v if len(v) == 3 else 'und')


def lang_name(code):
    return LANGS.get(code, (code.upper() if code and code != 'und' else '',))[0]


# ------------------------------------------------------------ externe Dateien
def external(video_path):
    """Liste der Untertiteldateien neben dem Film (sortiert, stabil)."""
    src = Path(video_path)
    try:
        entries = [e for e in os.scandir(src.parent) if e.is_file(follow_symlinks=False)]
    except OSError:
        return []
    vids = [e for e in entries if Path(e.name).suffix.lower() in S.VIDEO]
    only_one = len(vids) <= 1
    stem = src.stem.lower()
    out = []
    for e in sorted(entries, key=lambda x: x.name.lower()):
        p = Path(e.name)
        ext = p.suffix.lower()
        if ext not in SUB_EXT:
            continue
        name = p.stem
        low = name.lower()
        if low == stem or low.startswith(stem + '.') or low.startswith(stem + '_') or low.startswith(stem + ' '):
            tags = low[len(stem):]
        elif only_one:
            tags = low
        else:
            continue
        try:
            if e.stat().st_size > MAX_SUB_BYTES:
                continue
        except OSError:
            continue
        parts = [t for t in re.split(r'[.\s_\-\[\]()]+', tags) if t]
        code = next((_ALIAS[t] for t in parts if t in _ALIAS), 'und')
        out.append({'path': str(src.parent / e.name), 'codec': SUB_EXT[ext], 'language': code,
                    'forced': any(t in FORCED for t in parts), 'sdh': any(t in SDH for t in parts),
                    'default': 'default' in parts})
    return out


# ------------------------------------------------------------ Text einlesen
def read_text(path):
    raw = Path(path).read_bytes()[:MAX_SUB_BYTES]
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        return raw.decode('utf-16', 'replace')
    try:
        return raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        return raw.decode('cp1252', 'replace')


_T = r'(?:(\d+):)?(\d{1,2}):(\d{1,2})[.,](\d{1,3})'
_CUE = re.compile(_T + r'\s*-->\s*' + _T)


def _sec(h, m, s, f):
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(f.ljust(3, '0')[:3]) / 1000


def parse_srt_vtt(text):
    cues = []
    for block in re.split(r'\n\s*\n', text.replace('\r\n', '\n').replace('\r', '\n')):
        lines = block.strip('\n').split('\n')
        for i, ln in enumerate(lines):
            m = _CUE.search(ln)
            if m:
                g = m.groups()
                body = '\n'.join(lines[i + 1:]).strip()
                if body:
                    cues.append((_sec(*g[:4]), _sec(*g[4:]), body))
                break
    return cues


def parse_ass(text):
    cues, fmt, in_events = [], None, False
    for ln in text.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        s = ln.strip()
        if s.startswith('['):
            in_events = s.lower() == '[events]'
            continue
        if not in_events:
            continue
        if s.lower().startswith('format:'):
            fmt = [x.strip().lower() for x in s[7:].split(',')]
        elif s.lower().startswith('dialogue:') and fmt:
            vals = s[9:].lstrip().split(',', len(fmt) - 1)
            if len(vals) < len(fmt):
                continue
            d = dict(zip(fmt, vals))
            try:
                a = [float(x) for x in d['start'].strip().split(':')]
                b = [float(x) for x in d['end'].strip().split(':')]
            except (KeyError, ValueError):
                continue
            st, en = a[0] * 3600 + a[1] * 60 + a[2], b[0] * 3600 + b[1] * 60 + b[2]
            body = re.sub(r'\{[^}]*\}', '', d.get('text', ''))
            body = body.replace('\\N', '\n').replace('\\n', '\n').replace('\\h', ' ').strip()
            if body:
                cues.append((st, en, body))
    cues.sort(key=lambda c: c[0])
    return cues


def _ts(sec, sep='.'):
    ms = int(round(max(0.0, sec) * 1000))
    return '%02d:%02d:%02d%s%03d' % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, sep, ms % 1000)


def to_vtt(cues):
    out = ['WEBVTT', '']
    for st, en, body in cues:
        out += ['%s --> %s' % (_ts(st), _ts(en)), body.replace('-->', '->'), '']
    return '\n'.join(out)


def to_srt(cues):
    out = []
    for n, (st, en, body) in enumerate(cues, 1):
        out += [str(n), '%s --> %s' % (_ts(st, ','), _ts(en, ',')), body, '']
    return '\n'.join(out)


def to_ass(cues):
    head = ('[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\n\n[V4+ Styles]\n'
            'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, '
            'Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n'
            'Style: Default,Arial,64,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,3,1,2,60,60,50,1\n\n'
            '[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n')

    def t(sec):
        cs = int(round(max(0.0, sec) * 100))
        return '%d:%02d:%02d.%02d' % (cs // 360000, cs // 6000 % 60, cs // 100 % 60, cs % 100)
    return head + ''.join('Dialogue: 0,%s,%s,Default,,0,0,0,,%s\n' % (t(st), t(en), re.sub(r'<[^>]+>', '', b).replace('\n', '\\N'))
                          for st, en, b in cues)


def to_js(cues):
    return json.dumps({'TrackEvents': [{'Id': str(n), 'Text': b, 'StartPositionTicks': int(st * TICKS),
                                        'EndPositionTicks': int(en * TICKS)} for n, (st, en, b) in enumerate(cues)]},
                      ensure_ascii=False)


# ------------------------------------------------------------ eingebettete Spuren
_extract_lock = threading.Lock()
_key_locks = {}


def _cache_dir():
    d = S.DATA / 'subcache'
    d.mkdir(parents=True, exist_ok=True)
    return d


def extract(o, idx, codec):
    """Spur idx einmal herauslösen. Rückgabe: Pfad zur Datei (.srt/.ass/.sup) oder None."""
    import jf_api
    ff = jf_api.ffmpeg_bin()
    if not ff:
        return None
    if codec in ('ass', 'ssa'):
        ext, args = '.ass', ['-c:s', 'copy', '-f', 'ass']
    elif codec in IMAGE_OK:
        ext, args = '.sup', ['-c:s', 'copy', '-f', 'sup']
    elif codec == 'subrip':
        ext, args = '.srt', ['-c:s', 'copy', '-f', 'srt']
    else:
        ext, args = '.srt', ['-c:s', 'srt', '-f', 'srt']
    try:
        mt = os.stat(o['path']).st_mtime_ns
    except OSError:
        return None
    target = _cache_dir() / ('%s_%x_%d%s' % (o['mid'], mt, idx, ext))
    if target.is_file():
        return target
    with _extract_lock:
        lock = _key_locks.setdefault(str(target), threading.Lock())
    with lock:
        if target.is_file():
            return target
        for old in _cache_dir().glob('%s_*_%d.*' % (o['mid'], idx)):   # alte Fassung (Datei geändert)
            try:
                old.unlink()
            except OSError:
                pass
        tmp = target.with_suffix(ext + '.part')
        cmd = [ff, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y', '-i', o['path'], '-map', '0:%d' % idx,
               '-vn', '-an', '-dn'] + args + [str(tmp)]
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1800, check=True)
            os.replace(str(tmp), str(target))
        except Exception as e:
            print('JF Untertitel: Herauslösen fehlgeschlagen', Path(o['path']).name, idx, type(e).__name__, flush=True)
            try:
                tmp.unlink()
            except OSError:
                pass
            return None
    return target


# ------------------------------------------------------------ Streams für PlaybackInfo
def streams(o, first_index, token=''):
    """Untertitel-Streams (eingebettet + extern) im Jellyfin-Format."""
    out = []
    known = o.get('streams') or []
    for i, st in enumerate(known):
        if st['type'] != 'Subtitle':
            continue
        codec = (st.get('codec') or '').lower()
        text = codec in TEXT_CODECS
        if not text and codec not in IMAGE_OK:
            continue                                     # z. B. DVD-Untertitel: kann kein Client ohne Umrechnung
        out.append(_dto(o, i, codec, lang_code(st.get('language')), st.get('title') or '', False,
                        bool(st.get('forced')), bool(st.get('default')), bool(st.get('sdh')), token))
    for k, x in enumerate(external(o['path'])):
        out.append(_dto(o, first_index + k, x['codec'], x['language'], '', True, x['forced'], x['default'], x['sdh'], token))
    return out


def _dto(o, idx, codec, lang, title, ext, forced, default, sdh, token):
    shown = {'subrip': 'SRT', 'webvtt': 'VTT', 'mov_text': 'SRT', 'pgssub': 'PGS'}.get(codec, codec.upper())
    name = lang_name(lang) or 'Unbekannt'
    extra = [x for x in (title, 'Erzwungen' if forced else '', 'Hörgeschädigte' if sdh else '', shown, 'Extern' if ext else '') if x]
    fmt = 'ass' if codec in ('ass', 'ssa') else 'sup' if codec in IMAGE_OK else 'vtt'
    out_codec = codec if codec in ('ass', 'ssa', 'pgssub') else 'subrip' if codec == 'mov_text' else codec
    return {'Type': 'Subtitle', 'Index': idx, 'Codec': out_codec, 'Language': lang, 'Title': title or None,
            'DisplayTitle': name + ' - ' + ' - '.join(extra), 'LocalizedForced': 'Erzwungen', 'LocalizedExternal': 'Extern',
            'LocalizedDefault': 'Standard', 'LocalizedUndefined': 'Unbekannt',
            'IsDefault': default, 'IsForced': forced, 'IsHearingImpaired': sdh, 'IsExternal': ext,
            'IsTextSubtitleStream': codec in TEXT_CODECS, 'SupportsExternalStream': True,
            'DeliveryMethod': 'External', 'IsExternalUrl': False,
            'DeliveryUrl': '/Videos/%s/%s/Subtitles/%d/0/Stream.%s%s' % (o['jid'], o['jid'], idx, fmt,
                                                                       '?api_key=' + token if token else ''),
            'Path': None}


# ------------------------------------------------------------ Abruf
def find(o, idx):
    """(codec, quelle) – quelle = ('file', pfad) oder ('embedded', index)."""
    known = o.get('streams') or []
    if 0 <= idx < len(known) and known[idx]['type'] == 'Subtitle':
        return (known[idx].get('codec') or '').lower(), ('embedded', idx)
    first = len(known) if known else (2 if o['kind'] == 'video' else 1)
    ext = external(o['path'])
    k = idx - first
    if 0 <= k < len(ext):
        return ext[k]['codec'], ('file', ext[k]['path'])
    return None, None


def serve(h, o, idx, start_ticks, fmt):
    """Liefert Untertitel idx im gewünschten Format. True = beantwortet."""
    codec, src = find(o, idx)
    if not src:
        return h.send(404, b'{"error":"NOT_FOUND"}', 'application/json', {})
    fmt = (fmt or 'vtt').lower()
    path = src[1] if src[0] == 'file' else extract(o, idx, codec)
    if not path:
        return h.send(500, b'{"error":"SUBTITLE_EXTRACT_FAILED"}', 'application/json', {})
    if codec in IMAGE_OK:
        data = Path(path).read_bytes()
        return h.send(200, data, 'application/octet-stream', {'Cache-Control': 'private, max-age=3600'})
    text = read_text(path)
    is_ass = codec in ('ass', 'ssa') or str(path).lower().endswith(('.ass', '.ssa'))
    if fmt in ('ass', 'ssa') and is_ass and not start_ticks:
        return h.send(200, text.encode('utf-8'), 'text/x-ssa; charset=utf-8', {'Cache-Control': 'private, max-age=3600'})
    cues = parse_ass(text) if is_ass else parse_srt_vtt(text)
    if start_ticks:
        off = start_ticks / TICKS
        cues = [(st - off, en - off, b) for st, en, b in cues if en > off]
    if fmt == 'js' or fmt == 'json':
        body, mime = to_js(cues), 'application/json'
    elif fmt == 'srt':
        body, mime = to_srt(cues), 'application/x-subrip'
    elif fmt in ('ass', 'ssa'):
        body, mime = to_ass(cues), 'text/x-ssa'
    else:
        body, mime = to_vtt(cues), 'text/vtt'
    return h.send(200, body.encode('utf-8'), mime + '; charset=utf-8', {'Cache-Control': 'private, max-age=3600'})
