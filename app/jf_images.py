"""Bildverwaltung („Bilder bearbeiten“ in der Jellyfin-Oberfläche).

Hochladen, Löschen, Reihenfolge ändern, anderes Bild aus TMDb wählen.
Die Dateien des Nutzers neben den Filmen werden NIE verändert oder gelöscht: die Auswahl wird als Liste pro Bildart
in den eigenen Änderungen (Tabelle jf_edits, Feld „images“) gespeichert. Hochgeladene und ausgewählte Bilder liegen
in data/meta/user/. Nur solche eigenen Kopien werden beim Löschen wirklich entfernt.
"""
import base64
import binascii
import hashlib
import os
import secrets
import struct
import urllib.parse
from pathlib import Path

S = None       # server
A = None       # jf_api
M = None       # jf_meta

TYPES = ('Primary', 'Backdrop', 'Logo', 'Thumb', 'Banner', 'Art', 'Disc')
MULTI = ('Backdrop',)          # nur Hintergründe dürfen mehrere sein
MAX_BACKDROPS = 20
MAX_UPLOAD = 15 * 1024 * 1024
EDITABLE = ('Movie', 'Video', 'Episode', 'Series', 'Season', 'MusicAlbum')
TMDB_KIND = {'Primary': 'posters', 'Backdrop': 'backdrops', 'Logo': 'logos', 'Thumb': 'backdrops'}


def setup(server_module, api_module, meta_module):
    global S, A, M
    S, A, M = server_module, api_module, meta_module
    (S.DATA / 'meta' / 'user').mkdir(parents=True, exist_ok=True)


def _user_dir():
    return S.DATA / 'meta' / 'user'


def norm_type(t):
    for x in TYPES:
        if x.lower() == str(t or '').lower():
            return x
    return None


# ------------------------------------------------------------ Bildgröße ohne Zusatzprogramme
def size_of(data):
    """(breite, höhe, mime) aus den ersten Bytes. None, wenn kein bekanntes Bild."""
    try:
        if data[:8] == b'\x89PNG\r\n\x1a\n':
            w, h = struct.unpack('>II', data[16:24])
            return w, h, 'image/png'
        if data[:3] == b'\xff\xd8\xff':
            i = 2
            while i + 9 < len(data):
                if data[i] != 0xFF:
                    i += 1
                    continue
                mk = data[i + 1]
                if mk in (0xD8, 0x01) or 0xD0 <= mk <= 0xD7:
                    i += 2
                    continue
                ln = struct.unpack('>H', data[i + 2:i + 4])[0]
                if mk in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    h, w = struct.unpack('>HH', data[i + 5:i + 9])
                    return w, h, 'image/jpeg'
                i += 2 + ln
            return 0, 0, 'image/jpeg'
        if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            ch = data[12:16]
            if ch == b'VP8X':
                w = 1 + int.from_bytes(data[24:27], 'little'); h = 1 + int.from_bytes(data[27:30], 'little')
            elif ch == b'VP8L':
                b = int.from_bytes(data[21:25], 'little'); w = 1 + (b & 0x3FFF); h = 1 + ((b >> 14) & 0x3FFF)
            else:
                w, h = struct.unpack('<HH', data[26:30]); w &= 0x3FFF; h &= 0x3FFF
            return w, h, 'image/webp'
        if data[:6] in (b'GIF87a', b'GIF89a'):
            w, h = struct.unpack('<HH', data[6:10])
            return w, h, 'image/gif'
    except (struct.error, IndexError):
        pass
    return None


def file_info(path):
    try:
        with open(path, 'rb') as f:
            head = f.read(256 * 1024)
        st = os.stat(path)
    except OSError:
        return None
    si = size_of(head) or (0, 0, 'image/jpeg')
    return {'w': si[0], 'h': si[1], 'mime': si[2], 'size': st.st_size}


EXT = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp', 'image/gif': '.gif'}


# ------------------------------------------------------------ aktuelle Bilder eines Eintrags
def key_of(o):
    return o.get('mid') or o['jid']


def lists(o):
    """Die Bilder, wie sie gerade angezeigt werden – pro Bildart eine Liste von Pfaden."""
    out = {t: [] for t in TYPES}
    if o.get('cover'):
        out['Primary'] = [o['cover']]
    if o.get('backdrops'):
        out['Backdrop'] = [p for p, _ in o['backdrops']]
    elif o.get('backdrop'):
        out['Backdrop'] = [o['backdrop']]
    if o.get('logo'):
        out['Logo'] = [o['logo']]
    for t, (p, _) in (o.get('extra_images') or {}).items():
        out[t] = [p]
    return out


def apply_edit(o, imgs):
    """Gespeicherte Bildauswahl in ein Katalog-Objekt übernehmen (aufgerufen aus jf_meta.apply)."""
    for t, paths in imgs.items():
        t = norm_type(t)
        if not t or not isinstance(paths, list):
            continue
        ok = []
        for p in paths:
            tg = M._tag(p)
            if tg and Path(p).is_file():
                ok.append((p, tg))
        if t == 'Primary':
            o['cover'], o['cover_tag'] = ok[0] if ok else (None, None)
        elif t == 'Backdrop':
            o['backdrops'] = ok
            o['backdrop'], o['backdrop_tag'] = ok[0] if ok else (None, None)
            o['no_backdrop'] = not ok
        elif t == 'Logo':
            o['logo'], o['logo_tag'] = ok[0] if ok else (None, None)
        else:
            ex = o.setdefault('extra_images', {})
            if ok:
                ex[t] = ok[0]
            else:
                ex.pop(t, None)


def infos(o):
    """GET /Items/{id}/Images"""
    out = []
    for t, paths in lists(o).items():
        for i, p in enumerate(paths):
            fi = file_info(p)
            if not fi:
                continue
            out.append({'ImageType': t, 'ImageIndex': i if t in MULTI else None, 'ImageTag': M._tag(p),
                        'Path': A.show_path(p) if _inside_media(p) else ('Eigene Bilder/' if _own_copy(p) else 'TheMovieDb/') + Path(p).name,
                        'Width': fi['w'], 'Height': fi['h'], 'Size': fi['size'], 'BlurHash': None})
    return out


def _inside_media(p):
    try:
        return S.MEDIA.resolve() in Path(p).resolve().parents
    except OSError:
        return False


def _own_copy(p):
    try:
        return _user_dir().resolve() in Path(p).resolve().parents
    except OSError:
        return False


def _store(o, t, paths, removed=()):
    key = key_of(o)
    old = (M.load_edits().get(key) or {}).get('images') or {}
    old = {k: v for k, v in old.items() if norm_type(k)}
    old[t] = list(paths)
    M.save_edit(key, {'images': old})
    for p in removed:  # nur eigene Kopien wirklich löschen – nie Dateien im Medienordner
        if _own_copy(p) and p not in paths:
            try:
                os.unlink(p)
            except OSError:
                pass
    A.invalidate()


def _new_file(o, t, data, mime):
    name = '%s-%s-%s%s' % (key_of(o), t.lower(), secrets.token_hex(4), EXT.get(mime, '.jpg'))
    target = _user_dir() / name
    tmp = target.with_suffix(target.suffix + '.part')
    tmp.write_bytes(data)
    os.replace(str(tmp), str(target))
    return str(target)


def _add(o, t, path):
    cur = lists(o)[t]
    if t in MULTI:
        new = [path] + cur
        if len(new) > MAX_BACKDROPS:
            return _store(o, t, new[:MAX_BACKDROPS], new[MAX_BACKDROPS:])
        return _store(o, t, new)
    return _store(o, t, [path], cur)


def upload(h, o, t, user):
    """POST /Items/{id}/Images/{type} – Inhalt ist Base64 (so schickt es jellyfin-web)."""
    try:
        n = int(h.headers.get('Content-Length', '0'))
    except ValueError:
        n = 0
    if n <= 0 or n > MAX_UPLOAD * 4 // 3 + 16:
        if n > 0:
            h.rfile.read(n)
        return A.J(h, {'error': 'IMAGE_TOO_LARGE'}, 413)
    raw = h.rfile.read(n)
    try:
        data = base64.b64decode(raw.strip(), validate=False) if not size_of(raw[:64]) else raw
    except (binascii.Error, ValueError):
        return A.J(h, {'error': 'INVALID_IMAGE'}, 400)
    si = size_of(data[:256 * 1024])
    if not si or len(data) > MAX_UPLOAD or len(data) < 100:
        return A.J(h, {'error': 'INVALID_IMAGE'}, 400)
    _add(o, t, _new_file(o, t, data, si[2]))
    return A.none(h)


def delete(h, o, t, idx):
    cur = lists(o)[t]
    if t in MULTI and idx is not None:
        if not 0 <= idx < len(cur):
            return A.J(h, {'error': 'NOT_FOUND'}, 404)
        gone = [cur[idx]]
        keep = cur[:idx] + cur[idx + 1:]
    else:
        gone, keep = cur, []
    _store(o, t, keep, gone)
    return A.none(h)


def move(h, o, t, idx, new):
    cur = lists(o)[t]
    if not (0 <= idx < len(cur)) or not (0 <= new < len(cur)):
        return A.J(h, {'error': 'NOT_FOUND'}, 404)
    p = cur.pop(idx)
    cur.insert(new, p)
    _store(o, t, cur)
    return A.none(h)


# ------------------------------------------------------------ Bilder aus dem Netz (TMDb)
def providers(o):
    if not M.tmdb_on() or o['type'] not in ('Movie', 'Series', 'Season', 'Episode'):
        return []
    sup = ['Primary', 'Backdrop', 'Logo', 'Thumb'] if o['type'] in ('Movie', 'Series') else ['Primary']
    return [{'Name': 'TheMovieDb', 'SupportedImages': sup}]


def _tmdb_images(cat, o):
    """Rohliste {art: [bilder]} von TMDb für Film/Serie/Staffel/Folge."""
    def series_tid(sid):
        ser = cat['items'].get(sid) or {}
        return (ser.get('ids') or {}).get('tmdb')
    lang = M.settings()['Language'][:2]
    il = '%s,en,null' % lang
    t = o['type']
    if t in ('Movie', 'Series'):
        tid = (o.get('ids') or {}).get('tmdb')
        if not tid:
            return {}, lang
        return M.tmdb('/%s/%s/images' % ('tv' if t == 'Series' else 'movie', tid), include_image_language=il) or {}, lang
    if t == 'Season':
        tid = series_tid(o['series_id'])
        if not tid:
            return {}, lang
        return M.tmdb('/tv/%s/season/%d/images' % (tid, o['index']), include_image_language=il) or {}, lang
    if t == 'Episode':
        tid = series_tid(o['series_id'])
        if not tid or o.get('episode') is None:
            return {}, lang
        d = M.tmdb('/tv/%s/season/%d/episode/%d/images' % (tid, o['season'], o['episode'])) or {}
        return {'posters': d.get('stills') or []}, lang
    return {}, lang


def remote(cat, o, q):
    """GET /Items/{id}/RemoteImages"""
    want = norm_type(q.get('type')) or 'Primary'
    try:
        start = max(0, int(q.get('startindex') or 0)); limit = max(1, min(int(q.get('limit') or 30), 100))
    except ValueError:
        start, limit = 0, 30
    allang = str(q.get('includealllanguages', '')).lower() == 'true'
    res = {'Images': [], 'TotalRecordCount': 0, 'Providers': [x['Name'] for x in providers(o)]}
    if not res['Providers']:
        return res
    raw, lang = _tmdb_images(cat, o)
    kind = TMDB_KIND.get(want)
    lst = list(raw.get(kind) or []) if kind else []
    if want == 'Thumb':
        lst = [x for x in lst if x.get('iso_639_1')]  # Vorschaubild = Hintergrund mit Schriftzug
    if not allang:
        lst = [x for x in lst if x.get('iso_639_1') in (lang, 'en', None)]
    lst.sort(key=lambda x: (x.get('iso_639_1') != lang, x.get('iso_639_1') != 'en', -(x.get('vote_average') or 0)))
    res['TotalRecordCount'] = len(lst)
    for x in lst[start:start + limit]:
        fp = x.get('file_path') or ''
        res['Images'].append({'ProviderName': 'TheMovieDb', 'Url': M.TMDB_IMG + 'original' + fp,
                              'ThumbnailUrl': M.TMDB_IMG + 'w300' + fp, 'Height': x.get('height'), 'Width': x.get('width'),
                              'CommunityRating': x.get('vote_average'), 'VoteCount': x.get('vote_count'),
                              'Language': x.get('iso_639_1'), 'Type': want, 'RatingType': 'Score'})
    return res


def download_remote(h, o, q):
    """POST /Items/{id}/RemoteImages/Download?Type=…&ImageUrl=… – nur Bilder von TMDb."""
    t = norm_type(q.get('type'))
    url = str(q.get('imageurl') or '')
    if not t or not url.startswith(M.TMDB_IMG):
        return A.J(h, {'error': 'NOT_ALLOWED'}, 400)
    rest = url[len(M.TMDB_IMG):]
    size, _, fp = rest.partition('/')
    fp = '/' + fp
    if size not in ('original', 'w1280', 'w780', 'w500', 'w300') or not fp[1:] or '..' in fp or '?' in fp:
        return A.J(h, {'error': 'NOT_ALLOWED'}, 400)
    size = {'Primary': 'w780', 'Backdrop': 'w1280', 'Logo': 'w500', 'Thumb': 'w780'}.get(t, 'w780')
    target = _user_dir() / ('%s-%s-%s%s' % (key_of(o), t.lower(), hashlib.md5(fp.encode()).hexdigest()[:8],
                                            Path(urllib.parse.urlparse(fp).path).suffix.lower() or '.jpg'))
    got = M.download(fp, size, target)
    if not got:
        return h.send(502, 'Bild konnte nicht geladen werden'.encode(), 'text/plain; charset=utf-8', {})
    if not size_of(Path(got).read_bytes()[:256 * 1024]):
        os.unlink(got)
        return A.J(h, {'error': 'INVALID_IMAGE'}, 400)
    if got in lists(o)[t]:
        return A.none(h)
    _add(o, t, got)
    return A.none(h)


# ------------------------------------------------------------ Verteiler
def route(h, method, cat, o, rest, q, user):
    """rest = 'images…' bzw. 'remoteimages…'. Gibt None zurück, wenn es reine Bild-Abrufe sind."""
    parts = [x for x in rest.split('/') if x]
    if not user:
        if parts[0] == 'images' and len(parts) > 1 and method in ('GET', 'HEAD'):
            return None  # Bild-Abruf ohne Anmeldung ist erlaubt
        return A.J(h, {'error': 'AUTH_REQUIRED'}, 401)
    if parts[0] == 'remoteimages':
        if not o or o['type'] not in EDITABLE:
            return A.J(h, {'error': 'NOT_FOUND'}, 404)
        if user[2] != 'admin':
            return A.J(h, {'error': 'FORBIDDEN'}, 403)
        if len(parts) == 2 and parts[1] == 'providers':
            return A.J(h, providers(o))
        if len(parts) == 2 and parts[1] == 'download' and method == 'POST':
            try:
                return download_remote(h, o, q)
            except M.TmdbError as e:
                return h.send(502, str(e).encode(), 'text/plain; charset=utf-8', {})
        try:
            return A.J(h, remote(cat, o, q))
        except M.TmdbError as e:
            return h.send(502, str(e).encode(), 'text/plain; charset=utf-8', {})
    # parts[0] == 'images'
    if len(parts) == 1 and method == 'GET':
        if not o:
            return A.J(h, {'error': 'NOT_FOUND'}, 404)
        return A.J(h, infos(o) if o['type'] in EDITABLE else [])
    write = method in ('POST', 'DELETE')
    if not write:
        return None
    t = norm_type(parts[1]) if len(parts) > 1 else None
    if not o or not t or o['type'] not in EDITABLE:
        return A.J(h, {'error': 'NOT_FOUND'}, 404)
    if user[2] != 'admin':
        return A.J(h, {'error': 'FORBIDDEN'}, 403)
    idx = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
    if method == 'DELETE' or (len(parts) >= 3 and parts[-1] == 'delete'):
        return delete(h, o, t, idx)
    if len(parts) == 4 and parts[3] == 'index' and idx is not None:
        try:
            return move(h, o, t, idx, int(q.get('newindex')))
        except (TypeError, ValueError):
            return A.J(h, {'error': 'BAD_INDEX'}, 400)
    if len(parts) in (2, 3):
        return upload(h, o, t, user)
    return A.J(h, {'error': 'NOT_FOUND'}, 404)
