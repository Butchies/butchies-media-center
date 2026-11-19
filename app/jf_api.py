"""Jellyfin-kompatible Server-Schnittstelle für das Butchies Media Center.

Die originale Jellyfin-Weboberfläche (jellyfin-web, GPL) liegt in ./jfweb und spricht mit diesem Modul,
als wäre es ein Jellyfin-Server. Grund: Jellyfin (.NET) läuft auf der WD My Cloud EX2 Ultra nicht
(Kernel mit 32-KB-Speicherseiten), Python dagegen schon.

Etappe 1: Anmelden, Bibliotheken, Filme/Serien/Staffeln/Folgen/Musik, Bilder, Direktwiedergabe,
Weiterschauen, Gesehen, Favoriten.
"""
import hashlib, json, os, re, secrets, sqlite3, stat, threading, time, urllib.parse, uuid, mimetypes
from datetime import datetime, timezone
from pathlib import Path
import jf_subs
import jf_meta
import jf_ws
import jf_playlists
import jf_images
import jf_sessions
import sys as _sys

S = None  # das server-Modul (wird in setup() gesetzt)
SERVER_VERSION = '10.11.11'
PRODUCT = 'Butchies Media Center'
TICKS = 10_000_000
_cache = {'at': 0.0, 'data': None}
_cache_lock = threading.Lock()
_unknown_logged = set()


def setup(server_module):
    global S
    S = server_module
    jf_subs.setup(server_module)
    with S.sqlite_session(S.DATA / 'library.sqlite') as c:
        c.execute('CREATE TABLE IF NOT EXISTS jf_favorites (user_id INTEGER NOT NULL, item_id TEXT NOT NULL, PRIMARY KEY(user_id,item_id))')
        c.execute('CREATE TABLE IF NOT EXISTS jf_displayprefs (user_id INTEGER NOT NULL, pref_id TEXT NOT NULL, client TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(user_id,pref_id,client))')
        c.execute('CREATE TABLE IF NOT EXISTS jf_userconfig (user_id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS jf_probe (media_id TEXT PRIMARY KEY, mtime_ns INTEGER NOT NULL, duration REAL, streams TEXT NOT NULL)')
        if 'logo' not in {r[1] for r in c.execute('PRAGMA table_info(jf_probe)')}:
            c.execute('ALTER TABLE jf_probe ADD COLUMN logo TEXT')
            c.execute('DELETE FROM jf_probe')  # einmal neu einlesen, damit Logos gefunden werden
        if 'extra' not in {r[1] for r in c.execute('PRAGMA table_info(jf_probe)')}:
            c.execute('ALTER TABLE jf_probe ADD COLUMN extra TEXT')
            c.execute('DELETE FROM jf_probe')  # einmal genau neu einlesen (Bildrate, HDR, Kapitel, Kanäle)
    threading.Thread(target=_probe_loop, daemon=True).start()
    jf_meta.setup(server_module, _sys.modules[__name__])
    jf_images.setup(server_module, _sys.modules[__name__], jf_meta)
    jf_sessions.setup(server_module, _sys.modules[__name__])
    jf_playlists.setup(server_module, _sys.modules[__name__])
    if 'wizard_done' not in jf_settings() and S.accounts.count():
        save_setting('wizard_done', True)  # bestehende Installation: Einrichtung gilt als erledigt


LOGO_NAMES = ('logo.png', 'clearlogo.png', 'logo.webp', 'clearlogo.webp')


def find_logo(path):
    """Film-/Serienlogo (transparentes PNG) neben der Datei, im Ordner oder im Serienordner."""
    src = Path(path)
    cands = [src.with_name(src.stem + '-logo.png'), src.with_name(src.stem + '-clearlogo.png')]
    try:
        vids = sum(1 for e in os.scandir(src.parent) if e.is_file() and Path(e.name).suffix.lower() in S.VIDEO)
    except OSError:
        vids = 99
    if vids <= 1:  # Film im eigenen Ordner
        cands += [src.parent / n for n in LOGO_NAMES]
    if S.SEASON_FOLDER_RE.fullmatch(src.parent.name) or S.SERIES_RE.search(src.stem):  # Serie: Serienordner
        base = src.parent.parent if S.SEASON_FOLDER_RE.fullmatch(src.parent.name) else src.parent
        cands += [base / n for n in LOGO_NAMES]
    root = S.MEDIA.resolve()
    for c in cands:
        try:
            if c.is_file() and not c.is_symlink() and root in c.resolve().parents and c.stat().st_size <= S.COVER_MAX_BYTES:
                return str(c)
        except OSError:
            pass
    return None


def ffprobe_bin():
    for c in (S.ROOT / 'bin' / 'ffprobe', Path('/usr/bin/ffprobe'), Path('/usr/local/bin/ffprobe')):
        if c.is_file() and os.access(str(c), os.X_OK):
            return str(c)
    return None


def _fps(v):
    try:
        a, b = str(v or '0/0').split('/')
        return round(int(a) / int(b), 3) if int(b) else None
    except (ValueError, ZeroDivisionError):
        return None


def _hdr(st):
    """VideoRangeType wie Jellyfin: SDR, HDR10, HDR10Plus, HLG, DOVI, DOVIWithHDR10, DOVIWithHLG"""
    tr = st.get('color_transfer') or ''
    side = [x.get('side_data_type', '') for x in st.get('side_data_list') or []]
    dovi = any('DOVI' in x or 'Dolby Vision' in x for x in side)
    plus = any('HDR10+' in x or 'HDR Dynamic Metadata SMPTE2094-40' in x for x in side)
    if dovi:
        return 'DOVIWithHDR10' if tr == 'smpte2084' else 'DOVIWithHLG' if tr == 'arib-std-b67' else 'DOVI'
    if tr == 'smpte2084':
        return 'HDR10Plus' if plus else 'HDR10'
    if tr == 'arib-std-b67':
        return 'HLG'
    return 'SDR'


def ffprobe_details(path):
    """Genaue Technikdaten (Bildrate, HDR, Bit-Tiefe, Kanäle, Kapitel …) über das mitgelieferte ffprobe.
    Liest nur den Dateikopf – geht auch auf dem NAS schnell. None, wenn ffprobe fehlt oder scheitert."""
    fp = ffprobe_bin()
    if not fp:
        return None
    import subprocess
    try:
        r = subprocess.run([fp, '-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', '-show_chapters',
                            '-probesize', '10M', '-analyzeduration', '5M', str(path)],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=40)
        x = json.loads(r.stdout.decode('utf-8', 'replace') or '{}')
    except Exception:
        return None
    if not x.get('streams'):
        return None
    out = {'streams': [], 'chapters': [], 'bitrate': None, 'duration': None}
    fmt = x.get('format') or {}
    try:
        out['duration'] = float(fmt['duration'])
    except (KeyError, ValueError, TypeError):
        pass
    try:
        out['bitrate'] = int(fmt['bit_rate'])
    except (KeyError, ValueError, TypeError):
        pass
    for st in x['streams'][:60]:
        tags = {k.lower(): v for k, v in (st.get('tags') or {}).items()}
        disp = st.get('disposition') or {}
        ct = st.get('codec_type')
        typ = {'video': 'Video', 'audio': 'Audio', 'subtitle': 'Subtitle', 'attachment': 'Attachment'}.get(ct, 'Data')
        if typ == 'Video' and disp.get('attached_pic'):
            typ = 'EmbeddedImage'
        d = {'type': typ, 'codec': (st.get('codec_name') or '').lower(), 'language': (tags.get('language') or 'und')[:8],
             'title': str(tags.get('title') or '')[:120], 'default': bool(disp.get('default')), 'forced': bool(disp.get('forced')),
             'sdh': bool(disp.get('hearing_impaired'))}
        if st.get('profile'):
            d['profile'] = str(st['profile'])[:40]
        try:
            br = int(st.get('bit_rate') or tags.get('bps') or tags.get('bps-eng') or 0)
            if br:
                d['bitrate'] = br
        except (ValueError, TypeError):
            pass
        if typ == 'Video':
            pf = st.get('pix_fmt') or ''
            bd = st.get('bits_per_raw_sample')
            d.update(width=st.get('width'), height=st.get('height'), fps=_fps(st.get('r_frame_rate')),
                     avg_fps=_fps(st.get('avg_frame_rate')), pix_fmt=pf, level=st.get('level'),
                     bit_depth=int(bd) if str(bd or '').isdigit() else (10 if '10' in pf else 12 if '12' in pf else 8),
                     range=_hdr(st), color_transfer=st.get('color_transfer'), color_primaries=st.get('color_primaries'),
                     color_space=st.get('color_space'), aspect=st.get('display_aspect_ratio'),
                     interlaced=(st.get('field_order') or 'progressive') not in ('progressive', 'unknown'))
        elif typ == 'Audio':
            try:
                sr = int(st.get('sample_rate') or 0)
            except ValueError:
                sr = 0
            d.update(channels=st.get('channels'), layout=st.get('channel_layout'), sample_rate=sr or None)
        out['streams'].append(d)
    for i, c in enumerate(x.get('chapters') or []):
        try:
            start = float(c.get('start_time'))
        except (TypeError, ValueError):
            continue
        name = str(((c.get('tags') or {}).get('title')) or '').strip()[:120]
        out['chapters'].append({'start': round(start, 3), 'name': name or 'Kapitel %d' % (i + 1)})
    return out


def _probe_loop():
    """Liest im Hintergrund Laufzeit und Tonspuren aus den Dateien (ohne ffprobe, sparsam für das NAS)."""
    import videoinfo
    time.sleep(int(os.environ.get('BMC_PROBE_DELAY', '20')))
    while True:
        try:
            with S.sqlite_session(S.DATA / 'library.sqlite') as c:
                todo = c.execute('SELECT m.id,m.path,COALESCE(m.mtime_ns,0) FROM media m LEFT JOIN jf_probe p ON p.media_id=m.id '
                                 'WHERE p.media_id IS NULL OR p.mtime_ns!=COALESCE(m.mtime_ns,0) LIMIT 50').fetchall()
            for mid, path, mt in todo:
                info = videoinfo.details(path)
                full = ffprobe_details(path)
                extra = None
                if full:
                    info['streams'] = full['streams']
                    info['duration'] = full['duration'] or info['duration']
                    extra = json.dumps({'chapters': full['chapters'][:200], 'bitrate': full['bitrate']})
                logo = find_logo(path)
                with S.sqlite_session(S.DATA / 'library.sqlite') as c:
                    c.execute('INSERT OR REPLACE INTO jf_probe(media_id,mtime_ns,duration,streams,logo,extra) VALUES(?,?,?,?,?,?)',
                              (mid, mt, info['duration'], json.dumps(info['streams']), logo, extra))
                time.sleep(0.2)
            if todo:
                invalidate()
            time.sleep(5 if len(todo) == 50 else 120)
        except Exception as e:  # nie abstürzen
            print('JF probe:', type(e).__name__, str(e)[:120], flush=True)
            time.sleep(300)


def server_id():
    f = S.DATA / 'jf_server_id'
    try:
        v = f.read_text().strip()
        if re.fullmatch(r'[0-9a-f]{32}', v):
            return v
    except OSError:
        pass
    v = uuid.uuid4().hex
    try:
        f.write_text(v)
    except OSError:
        pass
    return v


# ---------------------------------------------------------------- IDs
def uid_of(user_id): return 'b0' + '%030x' % int(user_id)
def lib_of(lib_id): return 'c0' + '%030x' % int(lib_id)
def media_of(mid): return 'a0000000' + mid
def _h(*parts): return hashlib.md5('\x1f'.join(str(p) for p in parts).encode()).hexdigest()[:30]
def series_of(lib_id, name): return 'd0' + _h('series', lib_id, name.lower())
def season_of(series_id, season): return 'e0' + _h('season', series_id, season)
def artist_of(name): return '91' + _h('artist', name.lower())
def album_of(lib_id, folder): return 'f0' + _h('album', lib_id, folder.lower())


def norm_id(v):
    v = (v or '').replace('-', '').lower()
    return v if re.fullmatch(r'[0-9a-f]{32}', v) else ''


def iso(ts):
    try:
        return datetime.fromtimestamp(ts, timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.0000000Z')
    except (OverflowError, OSError, ValueError):
        return '2020-01-01T00:00:00.0000000Z'


# ---------------------------------------------------------------- Katalog
RELEASE_TOKENS = re.compile(r'(?i)^(?:2160p|1080p|1080i|720p|576p|480p|4k|uhd|hdr10?\+?|dv|german|deutsch|english|dl|ml|'
                            r'web(?:rip|-?dl)?|bluray|blu-ray|bdrip|brrip|dvdrip|hdtv|remux|x26[45]|h\.?26[45]|hevc|avc|xvid|'
                            r'aac(?:2\.0|5\.1)?|ac3|eac3|dd\+?(?:5\.1)?|dts(?:-?hd)?|truehd|atmos|proper|repack|extended|uncut|'
                            r'complete|internal|limited|dubbed|subbed|mic|ld|md)$')


def clean_name(raw):
    """'Allen.2026.German.WEBRip.DL.1080p.x265.AAC-2BA' -> ('Allen', 2026). Eigene Titel bleiben unberührt."""
    t = str(raw or '')
    if ' ' in t.strip() and not re.search(r'(?i)\b(1080p|720p|2160p|x26[45]|web-?dl|webrip|bluray)\b', t):
        m = re.search(r'\s*\(((?:19|20)\d\d)\)\s*$', t)
        return (t[:m.start()].strip() if m else t.strip()), (int(m.group(1)) if m else None)
    t = re.sub(r'-[A-Za-z0-9]+$', '', t) if re.search(r'(?i)(1080p|720p|2160p|x26[45]|web|bluray|german)', t) else t
    parts = [x for x in re.split(r'[._\s]+', t) if x]
    out, year = [], None
    for i, w in enumerate(parts):
        if re.fullmatch(r'\(?((?:19|20)\d\d)\)?', w) and i > 0:
            year = int(re.sub(r'\D', '', w)); break
        if i > 0 and RELEASE_TOKENS.match(w):
            break
        out.append(w)
    name = ' '.join(out).strip(' -') or str(raw)
    return name, year


def catalog():
    """Alle Medien als Jellyfin-Objekte (Filme, Folgen, Serien, Staffeln, Alben). 20 s zwischengespeichert."""
    with _cache_lock:
        if _cache['data'] is not None and time.time() - _cache['at'] < 20:
            return _cache['data']
    items, libs = {}, []
    with S.sqlite_session(S.DATA / 'library.sqlite') as c:
        c.row_factory = sqlite3.Row
        for r in c.execute('SELECT id,name,category,position FROM libraries WHERE enabled=1 ORDER BY position,name'):
            libs.append(dict(r))
        rows = [dict(r) for r in c.execute(
            "SELECT m.id,m.path,COALESCE(NULLIF(d.custom_title,''),m.title) AS title,(COALESCE(d.custom_title,'')!='') AS custom,m.kind,m.bytes,m.width,m.height,"
            "COALESCE(d.description,'') AS description,d.year,COALESCE(d.genre,'') AS genre,d.rating,m.cover_path,"
            "COALESCE(m.cover_ns,0) AS cover_ns,COALESCE(m.mtime_ns,0) AS mtime_ns,m.library_id,l.category AS library_category,"
            "pr.duration AS duration,pr.streams AS streams,pr.logo AS logo,pr.extra AS extra "
            "FROM media m JOIN libraries l ON l.id=m.library_id AND l.enabled=1 LEFT JOIN media_details d ON d.media_id=m.id "
            "LEFT JOIN jf_probe pr ON pr.media_id=m.id")]
        folders = {}
        for lib_id, path in c.execute('SELECT library_id,path FROM library_folders'):
            folders.setdefault(lib_id, []).append(path)
    root = S.MEDIA.resolve()
    lib_by_id = {l['id']: l for l in libs}
    for x in rows:
        path = x['path']
        try:
            rel = Path(path).relative_to(root)
            x['folder'] = str(rel.parent) if str(rel.parent) != '.' else 'Hauptordner'
            stem = rel.stem
            own = [f for f in folders.get(x['library_id'], []) if f == '' or rel.as_posix().startswith(f + '/')]
            parts = [p for p in (own[0] if own else '').split('/') if p]
        except ValueError:
            x['folder'] = 'Hauptordner'; stem = x['title']; parts = []
        S.classify_item(x, stem, parts)
        lid = x['library_id']
        jid = media_of(x['id'])
        ext = Path(path).suffix.lower().lstrip('.')
        nm, yr = clean_name(x['title'] or Path(path).stem) if (x['category'] != 'music' and not x.get('custom')) else (x['title'] or Path(path).stem, None)
        base = {
            'jid': jid, 'mid': x['id'], 'path': path, 'lib': lid, 'name': nm,
            'overview': x['description'], 'year': x['year'] or yr, 'genres': [g.strip() for g in (x['genre'] or '').split(',') if g.strip()],
            'rating': x['rating'], 'cover': x['cover_path'], 'cover_tag': ('%x' % (x['cover_ns'] or 1))[-12:] if x['cover_path'] else None,
            'date': (x['mtime_ns'] or 0) / 1e9, 'container': ext, 'width': x['width'], 'height': x['height'], 'bytes': x['bytes'],
            'kind': x['kind'], 'folder': False, 'parent': lib_of(lid), 'duration': x['duration'],
            'streams': json.loads(x['streams']) if x['streams'] else None,
            'extra': json.loads(x['extra']) if x.get('extra') else None,
            'logo': x['logo'], 'logo_tag': ('%x' % (x['mtime_ns'] or 1))[-10:] + 'l' if x['logo'] else None,
        }
        if x['category'] == 'music':
            album = x['folder']
            aid = album_of(lid, album)
            sub = Path(album).parts[len(parts):] if album != 'Hauptordner' else ()
            if len(sub) >= 2:
                artist = sub[-2]
            elif len(sub) == 1 and ' - ' in sub[0]:
                artist = sub[0].split(' - ', 1)[0].strip()
            else:
                artist = 'Unbekannter Künstler'
            base.update(type='Audio', parent=aid, album_id=aid, album=Path(album).name if album != 'Hauptordner' else 'Ohne Album',
                        artist=artist, artist_id=artist_of(artist))
            if aid not in items:
                items[aid] = {'jid': aid, 'type': 'MusicAlbum', 'folder': True, 'lib': lid, 'parent': lib_of(lid),
                              'name': base['album'], 'date': base['date'], 'children': [], 'cover': None, 'cover_tag': None,
                              'artist': artist, 'artist_id': artist_of(artist)}
            alb = items[aid]; alb['children'].append(jid); alb['date'] = max(alb['date'], base['date'])
            if not alb['cover'] and base['cover']:
                alb['cover'], alb['cover_tag'] = base['cover'], base['cover_tag']
        elif x['category'] == 'series':
            sname = x['series'] or 'Unbekannte Serie'
            sid = series_of(lid, sname)
            season = x['season'] if x['season'] is not None else 1
            zid = season_of(sid, season)
            base.update(type='Episode', parent=zid, series_id=sid, series=sname, season_id=zid, season=season, episode=x['episode'])
            if not x.get('custom'):
                mm = S.SERIES_RE.search(Path(path).stem)
                rest = clean_name(Path(path).stem[mm.end():])[0].strip(' -') if mm else ''
                if rest and rest != Path(path).stem:
                    base['name'] = rest
                elif x['episode'] is not None:
                    base['name'] = 'Folge %d' % x['episode']
            if sid not in items:
                items[sid] = {'jid': sid, 'type': 'Series', 'folder': True, 'lib': lid, 'parent': lib_of(lid), 'name': sname,
                              'date': base['date'], 'children': [], 'cover': None, 'cover_tag': None, 'year': x['year']}
            if zid not in items:
                items[zid] = {'jid': zid, 'type': 'Season', 'folder': True, 'lib': lid, 'parent': sid, 'series_id': sid,
                              'series': sname, 'index': season, 'name': 'Staffel %d' % season if season else 'Specials',
                              'date': base['date'], 'children': [], 'cover': None, 'cover_tag': None}
                items[sid]['children'].append(zid)
            ser, sea = items[sid], items[zid]
            sea['children'].append(jid)
            if not ser.get('logo') and base.get('logo'):
                ser['logo'], ser['logo_tag'] = base['logo'], base['logo_tag']
            for o in (ser, sea):
                o['date'] = max(o['date'], base['date'])
                if not o['cover'] and base['cover']:
                    o['cover'], o['cover_tag'] = base['cover'], base['cover_tag']
        else:
            base.update(type='Movie' if (lib_by_id.get(lid, {}).get('category') in ('movies', 'mixed')) else 'Video')
        items[jid] = base
    try:
        people = jf_meta.apply(items)
    except Exception as e:  # Metadaten dürfen den Katalog nie blockieren
        print('JF Metadaten (Katalog):', type(e).__name__, str(e)[:120], flush=True)
        people = {}
    for l in libs:
        jid = lib_of(l['id'])
        ctype = {'movies': 'movies', 'series': 'tvshows', 'music': 'music'}.get(l['category'], 'movies')
        items[jid] = {'jid': jid, 'type': 'CollectionFolder', 'folder': True, 'lib': l['id'], 'parent': None,
                      'name': l['name'], 'collection': ctype, 'date': 0, 'cover': None, 'cover_tag': None}
    # Bibliotheks-Kachel: Bild des neuesten Eintrags mit Cover
    for l in libs:
        lj = lib_of(l['id'])
        best = max((o for o in items.values() if o['lib'] == l['id'] and o.get('cover') and o['type'] in ('Movie', 'Video', 'Series', 'MusicAlbum')),
                   key=lambda o: o.get('date') or 0, default=None)
        if best:
            items[lj]['cover'], items[lj]['cover_tag'] = best['cover'], best['cover_tag']
    # Staffeln/Folgen sortieren
    for o in items.values():
        if o['type'] == 'Series':
            o['children'].sort(key=lambda z: items[z]['index'])
        elif o['type'] in ('Season', 'MusicAlbum'):
            o['children'].sort(key=lambda e: ((items[e].get('episode') or 0), items[e]['name'].lower()))
    for o in list(items.values()):
        if o['type'] in ('MusicAlbum', 'Audio') and o.get('artist_id'):
            ar = people.setdefault(o['artist_id'], {'jid': o['artist_id'], 'type': 'MusicArtist', 'name': o['artist'], 'folder': True,
                                                    'lib': o['lib'], 'parent': None, 'items': set(), 'date': 0, 'cover': None, 'cover_tag': None})
            ar['items'].add(o['jid'])
            if o['type'] == 'MusicAlbum' and o.get('cover') and not ar['cover']:
                ar['cover'], ar['cover_tag'] = o['cover'], o['cover_tag']
            ar['date'] = max(ar['date'], o.get('date') or 0)
    data = {'items': items, 'libs': [lib_of(l['id']) for l in libs], 'people': people}
    with _cache_lock:
        _cache['data'] = data; _cache['at'] = time.time()
    return data


def invalidate():
    with _cache_lock:
        _cache['data'] = None


# ---------------------------------------------------------------- Benutzerdaten
class UState(tuple):
    """(fortschritt, favoriten) + .dl = darf herunterladen"""
    dl = False


def may_download(user):
    """Herunterladen: Admins immer, andere nur, wenn im Dashboard › Benutzer › „Herunterladen erlauben“ angehakt."""
    if not user:
        return False
    if user[2] == 'admin':
        return True
    return user[0] in (jf_settings().get('download_users') or [])


def set_download(user_id, allowed):
    lst = [x for x in (jf_settings().get('download_users') or []) if x != user_id]
    if allowed:
        lst.append(user_id)
    save_setting('download_users', lst)


def _can_download(state):
    return bool(getattr(state, 'dl', False))


def user_state(user_id, user=None):
    with S.sqlite_session(S.DATA / 'library.sqlite') as c:
        prog = {r[0]: (r[1], r[2], r[3], r[4]) for r in c.execute(
            'SELECT media_id,position,duration,updated,completed FROM playback_progress WHERE user_id=?', (user_id,))}
        favs = {r[0] for r in c.execute('SELECT item_id FROM jf_favorites WHERE user_id=?', (user_id,))}
    st = UState((prog, favs))
    st.dl = may_download(user) if user else False
    return st


def leaf_ids(cat, o):
    if not o.get('folder'):
        return [o['jid']]
    if o['type'] == 'CollectionFolder':
        return [x['jid'] for x in cat['items'].values() if not x.get('folder') and x['lib'] == o['lib']]
    out = []
    for ch in o.get('children', []):
        out += leaf_ids(cat, cat['items'][ch])
    return out


def user_data(cat, o, state):
    prog, favs = state
    d = {'Key': o['jid'], 'ItemId': o['jid'], 'IsFavorite': o['jid'] in favs, 'PlayCount': 0, 'Played': False, 'PlaybackPositionTicks': 0}
    if o.get('type') in ('Person', 'MusicArtist'):
        return d
    if o.get('folder'):
        leaves = leaf_ids(cat, o)
        played = sum(1 for j in leaves if prog.get(cat['items'][j]['mid'], (0, 0, 0, 0))[3])
        d['UnplayedItemCount'] = max(0, len(leaves) - played)
        d['Played'] = bool(leaves) and played == len(leaves)
        if leaves:
            d['PlayedPercentage'] = round(100.0 * played / len(leaves), 1)
        return d
    p = prog.get(o['mid'])
    if p:
        pos, dur, upd, done = p
        d['Played'] = bool(done); d['PlayCount'] = 1 if done else 0
        full = o.get('duration') or dur
        if full and pos >= full * 0.9:
            d['Played'] = True; d['PlayCount'] = 1; done = True
        if not done and pos > 0:
            d['PlaybackPositionTicks'] = int(pos * TICKS)
            if dur:
                d['PlayedPercentage'] = round(100.0 * pos / dur, 1)
        d['LastPlayedDate'] = iso(upd)
    return d


def runtime_ticks(o, state):
    if o.get('duration'):
        return int(o['duration'] * TICKS)
    p = state[0].get(o.get('mid'))
    return int(p[1] * TICKS) if p and p[1] else None


def show_path(p):
    """Pfad wie in Emby („Identifizieren“, Medieninfo): ab dem Medienordner, z. B. Public/FULL HD CINEMA/x265/Film.mkv."""
    try:
        return str(Path(S.MEDIA.name) / Path(p).resolve().relative_to(S.MEDIA.resolve()))
    except (ValueError, OSError):
        return Path(p).name


def dto(cat, o, state, sid, full=False):
    t = o['type']
    d = {'Name': o['name'], 'ServerId': sid, 'Id': o['jid'], 'Type': t, 'IsFolder': bool(o.get('folder')),
         'DateCreated': iso(o.get('date') or 0), 'SortName': (o.get('sort_name') or o['name'] or '').lower(), 'LocationType': 'FileSystem',
         'ChannelId': None, 'CanDelete': False, 'CanDownload': not o.get('folder') and _can_download(state),
         'ImageTags': {}, 'BackdropImageTags': [], 'ImageBlurHashes': {}, 'UserData': user_data(cat, o, state)}
    if o.get('parent'):
        d['ParentId'] = o['parent']
    if o.get('cover_tag'):
        d['ImageTags']['Primary'] = o['cover_tag']
        # Card artwork proportions supplied to the web interface.
        if t in ('Movie', 'Series', 'Season', 'BoxSet'):
            d['PrimaryImageAspectRatio'] = 2 / 3
        elif t in ('Episode', 'Video', 'Program', 'TvChannel'):
            d['PrimaryImageAspectRatio'] = 16 / 9
        elif t in ('MusicAlbum', 'Audio', 'MusicArtist', 'Person'):
            d['PrimaryImageAspectRatio'] = 1.0
    if o.get('backdrops'):
        d['BackdropImageTags'] = [tg for _, tg in o['backdrops']]
    elif t in ('Movie', 'Series', 'Video') and not o.get('no_backdrop') and (o.get('backdrop_tag') or o.get('cover_tag')):
        d['BackdropImageTags'] = [o.get('backdrop_tag') or o['cover_tag']]
    for k, (_, tg) in (o.get('extra_images') or {}).items():
        d['ImageTags'][k] = tg
    if t == 'MusicArtist':
        its = [cat['items'][i] for i in o.get('items', ()) if i in cat['items']]
        d.update(AlbumCount=sum(1 for x in its if x['type'] == 'MusicAlbum'), SongCount=sum(1 for x in its if x['type'] == 'Audio'),
                 ChildCount=sum(1 for x in its if x['type'] == 'MusicAlbum'))
        if full:
            d.update(People=[], Studios=[], Genres=[], GenreItems=[], Taglines=[], ProviderIds={}, ExternalUrls=[], LockedFields=[],
                     LockData=False, Tags=[], RemoteTrailers=[])
        return d
    if t == 'Person':
        its = [cat['items'][i] for i in o.get('items', ()) if i in cat['items']]
        d.update(MovieCount=sum(1 for x in its if x['type'] == 'Movie'), SeriesCount=sum(1 for x in its if x['type'] == 'Series'),
                 EpisodeCount=sum(1 for x in its if x['type'] == 'Episode'), ChildCount=len(its))
        if full:
            d.update(People=[], Studios=[], Genres=[], GenreItems=[], Taglines=[], ProviderIds={'Tmdb': str(o['tmdb'])} if o.get('tmdb') else {},
                     ExternalUrls=[], LockedFields=[], LockData=False, Tags=[], RemoteTrailers=[])
        return d
    if o.get('logo_tag'):
        d['ImageTags']['Logo'] = o['logo_tag']
    if t == 'CollectionFolder':
        d['CollectionType'] = o['collection']; d['CanDownload'] = False
        d['Etag'] = o['jid'][:16]
    if o.get('year'):
        d['ProductionYear'] = o['year']; d['PremiereDate'] = '%04d-01-01T00:00:00.0000000Z' % o['year']
    if o.get('overview'):
        d['Overview'] = o['overview']
    if o.get('genres'):
        d['Genres'] = o['genres']; d['GenreItems'] = [{'Name': g, 'Id': _h('genre', g) + '00'} for g in o['genres']]
    if o.get('rating'):
        d['CommunityRating'] = o['rating']
    if o.get('premiere'):
        d['PremiereDate'] = o['premiere'][:10] + 'T00:00:00.0000000Z'
    if o.get('official_rating'):
        d['OfficialRating'] = o['official_rating']
    if o.get('original_title'):
        d['OriginalTitle'] = o['original_title']
    if o.get('ids'):
        d['ProviderIds'] = {{'tmdb': 'Tmdb', 'imdb': 'Imdb', 'tvdb': 'Tvdb'}[k]: v for k, v in o['ids'].items() if k in ('tmdb', 'imdb', 'tvdb')}
    if not o.get('folder'):
        d['MediaType'] = 'Audio' if o['kind'] == 'audio' else 'Video'
        d['Container'] = o['container']
        rt = runtime_ticks(o, state)
        if rt:
            d['RunTimeTicks'] = rt
        if d['MediaType'] == 'Video':
            d['VideoType'] = 'VideoFile'
            if o.get('width'):
                d['Width'] = o['width']; d['Height'] = o['height']
        d['HasSubtitles'] = bool(o.get('streams') and any(x['type'] == 'Subtitle' for x in o['streams']))
        d['PlayAccess'] = 'Full'
        d['LocationType'] = 'FileSystem'
    if t == 'Episode':
        ser = cat['items'].get(o['series_id'], {})
        d.update(SeriesName=o['series'], SeriesId=o['series_id'], SeasonId=o['season_id'], ParentIndexNumber=o['season'],
                 SeasonName='Staffel %d' % o['season'] if o['season'] else 'Specials')
        if o.get('episode') is not None:
            d['IndexNumber'] = o['episode']
        if ser.get('cover_tag'):
            d['SeriesPrimaryImageTag'] = ser['cover_tag']
        if ser.get('backdrop_tag') or ser.get('cover_tag'):
            d['ParentBackdropItemId'] = o['series_id']; d['ParentBackdropImageTags'] = [ser.get('backdrop_tag') or ser['cover_tag']]
        if ser.get('logo_tag'):
            d['ParentLogoItemId'] = o['series_id']; d['ParentLogoImageTag'] = ser['logo_tag']
    if t == 'Season':
        d.update(IndexNumber=o['index'], SeriesId=o['series_id'], SeriesName=o['series'], ChildCount=len(o['children']))
        ser = cat['items'].get(o['series_id'], {})
        if ser.get('cover_tag'):
            d['SeriesPrimaryImageTag'] = ser['cover_tag']
    if t == 'Series':
        d['ChildCount'] = len(o['children']); d['RecursiveItemCount'] = len(leaf_ids(cat, o)); d['Status'] = o.get('status') or 'Ended'
        d['AirDays'] = []
    if t in ('Playlist', 'BoxSet'):
        d.update(ChildCount=len(o['children']), CanDelete=True)
        if t == 'Playlist':
            d['MediaType'] = o.get('media_type') or 'Video'
    if t == 'MusicAlbum':
        d['ChildCount'] = len(o['children'])
        ai = [{'Name': o.get('artist') or '', 'Id': o.get('artist_id')}] if o.get('artist_id') else []
        d.update(Artists=[x['Name'] for x in ai], ArtistItems=ai, AlbumArtist=o.get('artist') or '', AlbumArtists=ai)
    if t == 'Audio':
        ai = [{'Name': o.get('artist') or '', 'Id': o.get('artist_id')}] if o.get('artist_id') else []
        d.update(Album=o['album'], AlbumId=o['album_id'], Artists=[x['Name'] for x in ai], ArtistItems=ai,
                 AlbumArtist=o.get('artist') or '', AlbumArtists=ai)
        alb = cat['items'].get(o['album_id'], {})
        if alb.get('cover_tag'):
            d['AlbumPrimaryImageTag'] = alb['cover_tag']
    if full and not o.get('folder'):
        d['MediaSources'] = [media_source(o, state)]
        d['Path'] = show_path(o['path'])
        d['RemoteTrailers'] = []; d['ExternalUrls'] = []
        d['MediaStreams'] = d['MediaSources'][0]['MediaStreams']
        ch = chapters(o)
        if ch:
            d['Chapters'] = ch
    if full:
        pe = cat.get('people', {})
        d['People'] = [dict(x, PrimaryImageTag=pe[x['Id']]['cover_tag']) if pe.get(x['Id'], {}).get('cover_tag') else dict(x)
                       for x in o.get('people') or []]
        d['Studios'] = [{'Name': n, 'Id': _h('studio', n) + '00'} for n in o.get('studios') or []]
        d['Taglines'] = [o['tagline']] if o.get('tagline') else []
        d.setdefault('People', []); d.setdefault('Studios', []); d.setdefault('Tags', []); d.setdefault('GenreItems', [])
        d.setdefault('RemoteTrailers', []); d.setdefault('ProviderIds', {}); d.setdefault('ExternalUrls', [])
        d['Tags'] = list(o.get('tags') or [])
        d['ProductionLocations'] = list(o.get('countries') or [])
        if o.get('sort_name'):
            d['ForcedSortName'] = o['sort_name']
        d['LockedFields'] = list(o.get('locked') or []); d['LockData'] = bool(o.get('lock_data'))
    return d


def blocked(o):
    return o['kind'] == 'video' and (not o.get('width') or not o.get('height') or o['width'] > 1920 or o['height'] > 1080)


AUDIO_NAMES = {'ac3': 'Dolby Digital', 'eac3': 'Dolby Digital+', 'truehd': 'Dolby TrueHD', 'dts': 'DTS', 'aac': 'AAC',
               'mp3': 'MP3', 'flac': 'FLAC', 'opus': 'Opus', 'vorbis': 'Vorbis', 'pcm_s16le': 'PCM', 'pcm_s24le': 'PCM', 'alac': 'ALAC'}
LAYOUTS = {1: 'Mono', 2: 'Stereo', 3: '2.1', 6: '5.1', 7: '6.1', 8: '7.1'}


def stream_dto(o, i, st):
    """Eine Video-/Tonspur im Jellyfin-Format – mit allen Angaben, die ffprobe geliefert hat."""
    lang = st.get('language') or 'und'
    codec = st.get('codec') or ''
    d = {'Type': st['type'], 'Index': i, 'Codec': codec, 'Language': lang, 'Title': st.get('title') or None,
         'IsDefault': bool(st.get('default', True)), 'IsExternal': False, 'SupportsExternalStream': False,
         'IsForced': bool(st.get('forced')), 'IsHearingImpaired': bool(st.get('sdh')), 'IsTextSubtitleStream': False,
         'IsInterlaced': bool(st.get('interlaced')), 'IsAVC': codec == 'h264'}
    if st.get('profile'):
        d['Profile'] = st['profile']
    if st.get('bitrate'):
        d['BitRate'] = st['bitrate']
    if st['type'] == 'Video':
        w, hgt = st.get('width') or o.get('width'), st.get('height') or o.get('height')
        rng = st.get('range') or 'SDR'
        d.update(Width=w, Height=hgt, VideoRange='SDR' if rng == 'SDR' else 'HDR', VideoRangeType=rng)
        for k, src in (('RealFrameRate', 'fps'), ('AverageFrameRate', 'avg_fps'), ('BitDepth', 'bit_depth'), ('Level', 'level'),
                       ('PixelFormat', 'pix_fmt'), ('ColorTransfer', 'color_transfer'), ('ColorPrimaries', 'color_primaries'),
                       ('ColorSpace', 'color_space'), ('AspectRatio', 'aspect')):
            if st.get(src) not in (None, ''):
                d[k] = st[src]
        if rng.startswith('DOVI'):
            d['VideoDoViTitle'] = 'Dolby Vision'
        res = ('4K' if (w or 0) >= 3200 or (hgt or 0) >= 2000 else '%dp' % hgt if hgt else '')
        hdr = {'SDR': '', 'HDR10': 'HDR10', 'HDR10Plus': 'HDR10+', 'HLG': 'HLG'}.get(rng, 'Dolby Vision' if rng.startswith('DOVI') else 'HDR')
        d['DisplayTitle'] = ' '.join(x for x in (res, {'hevc': 'HEVC', 'h264': 'H.264', 'av1': 'AV1'}.get(codec, codec.upper()), hdr) if x)
    else:
        ch = st.get('channels') or 2
        d.update(Channels=ch, ChannelLayout=st.get('layout') or LAYOUTS.get(ch, '%d ch' % ch))
        if st.get('sample_rate'):
            d['SampleRate'] = st['sample_rate']
        name = jf_subs.lang_name(jf_subs.lang_code(lang)) if lang != 'und' else ''
        label = AUDIO_NAMES.get(codec, codec.upper())
        if codec == 'dts' and 'MA' in (st.get('profile') or ''):
            label = 'DTS-HD MA'
        d['DisplayTitle'] = ' - '.join(x for x in (st.get('title') if st.get('title') and st.get('title') != name else '',
                                                   name, label, LAYOUTS.get(ch, '%d Kanäle' % ch),
                                                   'Standard' if st.get('default') else '') if x) or label
    return d


def chapters(o):
    """Kapitel aus der Datei (Jellyfin: Chapters mit StartPositionTicks)."""
    ex = o.get('extra') or {}
    return [{'StartPositionTicks': int(c['start'] * TICKS), 'Name': c.get('name') or '', 'ImageDateModified': '0001-01-01T00:00:00.0000000Z'}
            for c in ex.get('chapters') or []]


def media_source(o, state, token=''):
    ext = o['container']
    streams = []
    known = o.get('streams')
    if known:
        for i, st in enumerate(known):
            if st['type'] not in ('Video', 'Audio'):
                continue  # Untertitel liefert jf_subs (mit Abruf-Adresse); Anhänge/Cover-Bilder nicht zeigen
            streams.append(stream_dto(o, i, st))
    elif o['kind'] == 'video':
        streams.append({'Type': 'Video', 'Index': 0, 'IsDefault': True, 'Width': o.get('width'), 'Height': o.get('height'),
                        'Codec': '', 'DisplayTitle': '%sp' % (o.get('height') or ''), 'IsExternal': False, 'SupportsExternalStream': False})
        streams.append({'Type': 'Audio', 'Index': 1, 'IsDefault': True, 'Codec': '', 'Channels': 2, 'Language': 'und',
                        'DisplayTitle': 'Audio', 'IsExternal': False, 'SupportsExternalStream': False})
    else:
        streams.append({'Type': 'Audio', 'Index': 0, 'IsDefault': True, 'Codec': ext, 'Channels': 2, 'DisplayTitle': ext.upper(),
                        'IsExternal': False, 'SupportsExternalStream': False})
    if o['kind'] == 'video':
        try:
            streams += jf_subs.streams(o, len(known) if known else 2, token)
        except Exception as e:
            print('JF Untertitel:', type(e).__name__, str(e)[:120], flush=True)
    audio_idx = next((x['Index'] for x in streams if x['Type'] == 'Audio'), None)
    ms = {'Protocol': 'File', 'Id': o['jid'], 'Path': Path(o['path']).name, 'Type': 'Default', 'Container': ext,
          'Size': o.get('bytes') or 0, 'Name': o['name'], 'IsRemote': False, 'ETag': o['jid'][:16],
          'ReadAtNativeFramerate': False, 'IgnoreDts': False, 'IgnoreIndex': False, 'GenPtsInput': False,
          'SupportsTranscoding': False, 'SupportsDirectStream': True, 'SupportsDirectPlay': True, 'IsInfiniteStream': False,
          'RequiresOpening': False, 'RequiresClosing': False, 'RequiresLooping': False, 'SupportsProbing': False,
          'VideoType': 'VideoFile' if o['kind'] == 'video' else None, 'MediaStreams': streams, 'MediaAttachments': [],
          'Formats': [], 'RequiredHttpHeaders': {}, 'DefaultAudioStreamIndex': audio_idx,
          'TranscodingSubProtocol': 'http', 'HasSegments': False}
    br = (o.get('extra') or {}).get('bitrate')
    if br:
        ms['Bitrate'] = br
    rt = runtime_ticks(o, state)
    if rt:
        ms['RunTimeTicks'] = rt
    return ms


# ---------------------------------------------------------------- Benutzer
def user_dto(user, sid):
    uid = uid_of(user[0])
    cfg = load_userconfig(user[0])
    return {
        'Name': user[1], 'ServerId': sid, 'Id': uid, 'HasPassword': True, 'HasConfiguredPassword': True,
        'HasConfiguredEasyPassword': False, 'EnableAutoLogin': False, 'LastLoginDate': iso(time.time()),
        'LastActivityDate': iso(time.time()), 'Configuration': cfg,
        'Policy': {
            'IsAdministrator': user[2] == 'admin', 'IsHidden': True, 'IsDisabled': False, 'EnableCollectionManagement': False,
            'EnableSubtitleManagement': False, 'EnableLyricManagement': False, 'BlockedTags': [], 'AllowedTags': [],
            'EnableUserPreferenceAccess': True, 'AccessSchedules': [], 'BlockUnratedItems': [],
            'EnableRemoteControlOfOtherUsers': False, 'EnableSharedDeviceControl': False, 'EnableRemoteAccess': True,
            'EnableLiveTvManagement': False, 'EnableLiveTvAccess': False, 'EnableMediaPlayback': True,
            'EnableAudioPlaybackTranscoding': False, 'EnableVideoPlaybackTranscoding': False, 'EnablePlaybackRemuxing': False,
            'ForceRemoteSourceTranscoding': False, 'EnableContentDeletion': False, 'EnableContentDeletionFromFolders': [],
            'EnableContentDownloading': may_download(user), 'EnableSyncTranscoding': False, 'EnableMediaConversion': False,
            'EnabledDevices': [], 'EnableAllDevices': True, 'EnabledChannels': [], 'EnableAllChannels': True,
            'EnabledFolders': [], 'EnableAllFolders': True, 'InvalidLoginAttemptCount': 0, 'LoginAttemptsBeforeLockout': -1,
            'MaxActiveSessions': 0, 'EnablePublicSharing': False, 'BlockedMediaFolders': [], 'BlockedChannels': [],
            'RemoteClientBitrateLimit': 0, 'AuthenticationProviderId': 'Jellyfin.Server.Implementations.Users.DefaultAuthenticationProvider',
            'PasswordResetProviderId': 'Jellyfin.Server.Implementations.Users.DefaultPasswordResetProvider', 'SyncPlayAccess': 'None'}}


DEFAULT_USERCONFIG = {'AudioLanguagePreference': '', 'PlayDefaultAudioTrack': True, 'SubtitleLanguagePreference': '',
                      'DisplayMissingEpisodes': False, 'GroupedFolders': [], 'SubtitleMode': 'Default',
                      'DisplayCollectionsView': False, 'EnableLocalPassword': False, 'OrderedViews': [], 'LatestItemsExcludes': [],
                      'MyMediaExcludes': [], 'HidePlayedInLatest': True, 'RememberAudioSelections': True,
                      'RememberSubtitleSelections': True, 'EnableNextEpisodeAutoPlay': True, 'CastReceiverId': 'F007D354'}


def _lang_ok(stream_lang, pref):
    a, b = jf_subs.lang_code(stream_lang or ''), jf_subs.lang_code(pref or '')
    return bool(b) and b != 'und' and a == b


def pick_tracks(streams, cfg):
    """Ton- und Untertitelspur nach den Einstellungen des Benutzers wählen (Einstellungen → Wiedergabe / Untertitel):
    bevorzugte Tonsprache, „Standard-Tonspur abspielen“, Untertitel-Modus Standard/Immer/Nur erzwungene/Intelligent/Keine."""
    aud = [x for x in streams if x['Type'] == 'Audio']
    sub = [x for x in streams if x['Type'] == 'Subtitle']
    apref = cfg.get('AudioLanguagePreference') or ''
    a = next((x for x in aud if _lang_ok(x.get('Language'), apref)), None) if apref else None
    if not a and cfg.get('PlayDefaultAudioTrack', True):
        a = next((x for x in aud if x.get('IsDefault')), None)
    a = a or (aud[0] if aud else None)
    mode = cfg.get('SubtitleMode') or 'Default'
    spref = cfg.get('SubtitleLanguagePreference') or ''
    in_pref = [x for x in sub if _lang_ok(x.get('Language'), spref)] if spref else []
    forced = [x for x in (in_pref or sub) if x.get('IsForced')]
    s = None
    if mode == 'None':
        s = None
    elif mode == 'OnlyForced':
        s = forced[0] if forced else None
    elif mode == 'Always':
        s = (in_pref or sub or [None])[0]
    elif mode == 'Smart':  # Untertitel nur, wenn der Ton nicht in der Wunsch-Sprache ist
        if a and spref and not _lang_ok(a.get('Language'), spref):
            s = (in_pref or [None])[0]
        else:
            s = forced[0] if forced else None
    else:  # Standard: erzwungene oder als Standard markierte
        s = forced[0] if forced else next((x for x in (in_pref or sub) if x.get('IsDefault') and not x.get('IsExternal')), None)
    return (a['Index'] if a else None), (s['Index'] if s else -1)


def load_userconfig(user_id):
    with S.sqlite_session(S.DATA / 'library.sqlite') as c:
        r = c.execute('SELECT payload FROM jf_userconfig WHERE user_id=?', (user_id,)).fetchone()
    cfg = dict(DEFAULT_USERCONFIG)
    if r:
        try:
            cfg.update(json.loads(r[0]))
        except ValueError:
            pass
    return cfg


# ---------------------------------------------------------------- Anfrage-Helfer
def auth_token(h):
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(h.path).query)
    for k in ('api_key', 'ApiKey', 'apikey'):
        if q.get(k):
            return q[k][0]
    for hdr in ('X-Emby-Token', 'X-MediaBrowser-Token'):
        if h.headers.get(hdr):
            return h.headers.get(hdr)
    for hdr in ('Authorization', 'X-Emby-Authorization'):
        v = h.headers.get(hdr, '')
        m = re.search(r'Token="([^"]*)"', v)
        if m:
            return m.group(1)
        if v.startswith('Bearer '):
            return v[7:]
    return ''


def auth_fields(h):
    v = h.headers.get('Authorization', '') or h.headers.get('X-Emby-Authorization', '')
    return dict(re.findall(r'(\w+)="([^"]*)"', v))


def current_user(h):
    t = auth_token(h)
    return S.accounts.user(t) if t else None


def body_json(h, limit=1_000_000):
    try:
        n = int(h.headers.get('Content-Length', '0'))
    except ValueError:
        n = 0
    if n <= 0 or n > limit:
        if n > limit:
            h.rfile.read(n)
        return {}
    raw = h.rfile.read(n)
    try:
        d = json.loads(raw or b'{}')
        return d if isinstance(d, dict) else {}
    except ValueError:
        return {}


def J(h, obj, status=200):
    body = json.dumps(obj, ensure_ascii=False).encode()
    h.send(status, body, 'application/json; charset=utf-8', {'X-Frame-Options': 'SAMEORIGIN'})
    return True


def none(h):
    h.send(204, b'', 'text/plain', {})
    return True


def qparams(h):
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(h.path).query, keep_blank_values=True)
    return {k.lower(): v[-1] for k, v in q.items()}


def csv(v):
    return [x.strip() for x in (v or '').split(',') if x.strip()]


def truthy(v):
    return str(v).lower() == 'true'


# ---------------------------------------------------------------- Abfragen
SORTS = {
    'sortname': lambda o: (o.get('name') or '').lower(), 'name': lambda o: (o.get('name') or '').lower(),
    'datecreated': lambda o: o.get('date') or 0, 'premieredate': lambda o: o.get('year') or 0,
    'productionyear': lambda o: o.get('year') or 0, 'communityrating': lambda o: o.get('rating') or 0,
    'indexnumber': lambda o: o.get('episode') or o.get('index') or 0,
    'parentindexnumber': lambda o: o.get('season') or 0, 'runtime': lambda o: o.get('bytes') or 0,
}


def query_items(cat, q, user, state, forced_parent=None):
    items = cat['items']
    parent = norm_id(forced_parent or q.get('parentid', ''))
    types = {t.lower() for t in csv(q.get('includeitemtypes'))}
    exclude = {t.lower() for t in csv(q.get('excludeitemtypes'))}
    recursive = truthy(q.get('recursive'))
    ids = [norm_id(x) for x in csv(q.get('ids'))]
    media_types = {t.lower() for t in csv(q.get('mediatypes'))}
    if ids:
        pool = [items[i] for i in ids if i in items]
    elif norm_id((q.get('artistids') or q.get('albumartistids') or q.get('contributingartistids') or '').split(',')[0]):
        aid = norm_id((q.get('artistids') or q.get('albumartistids') or q.get('contributingartistids')).split(',')[0])
        ar = cat.get('people', {}).get(aid) or {}
        pool = [items[i] for i in ar.get('items', ()) if i in items]
        if q.get('albumartistids') and not q.get('includeitemtypes'):
            pool = [o for o in pool if o['type'] == 'MusicAlbum']
    elif norm_id(q.get('personids', '').split(',')[0]):
        pers = cat.get('people', {}).get(norm_id(q['personids'].split(',')[0]))
        pool = [items[i] for i in (pers or {}).get('items', ()) if i in items]
    elif parent:
        p = items.get(parent)
        if not p:
            return []
        if p['type'] == 'CollectionFolder':
            if recursive or types:
                pool = [o for o in items.values() if o['lib'] == p['lib'] and o['type'] != 'CollectionFolder']
            else:
                pool = [o for o in items.values() if o.get('parent') == parent]
        elif recursive:
            pool = [items[j] for j in leaf_ids(cat, p)]
            if p['type'] == 'Series':
                pool += [items[z] for z in p['children']]
        else:
            pool = [items[ch] for ch in p.get('children', [])]
    else:
        pool = [o for o in items.values() if o['type'] != 'CollectionFolder'] if (recursive or types) else [items[i] for i in cat['libs']]
    if not ids and not (parent and items.get(parent, {}).get('type') in ('Playlist', 'BoxSet') or parent in (jf_playlists.VIEW_ID, jf_playlists.BOX_VIEW_ID)):
        hide = {t for t in ('Playlist', 'BoxSet') if t.lower() not in types}
        if hide:
            pool = [o for o in pool if o['type'] not in hide]
    if types:
        pool = [o for o in pool if o['type'].lower() in types]
    if exclude:
        pool = [o for o in pool if o['type'].lower() not in exclude]
    if media_types:
        pool = [o for o in pool if not o.get('folder') and ('audio' if o['kind'] == 'audio' else 'video') in media_types]
    if q.get('isfolder') in ('true', 'false'):
        pool = [o for o in pool if bool(o.get('folder')) == truthy(q['isfolder'])]
    filters = {f.lower() for f in csv(q.get('filters'))}
    if truthy(q.get('isfavorite')):
        filters.add('isfavorite')
    if q.get('isplayed') == 'true':
        filters.add('isplayed')
    if q.get('isplayed') == 'false':
        filters.add('isunplayed')
    if filters:
        def ok(o):
            ud = user_data(cat, o, state)
            if 'isfavorite' in filters and not ud['IsFavorite']: return False
            if 'isplayed' in filters and not ud['Played']: return False
            if 'isunplayed' in filters and ud['Played']: return False
            if 'isresumable' in filters and not ud.get('PlaybackPositionTicks'): return False
            return True
        pool = [o for o in pool if ok(o)]
    term = (q.get('searchterm') or '').strip().lower()
    if term:
        pool = [o for o in pool if term in (o.get('name') or '').lower()]
    sw = (q.get('namestartswith') or '').lower()
    if sw:
        pool = [o for o in pool if (o.get('name') or '').lower().startswith(sw)]
    swo = (q.get('namestartswithorgreater') or '').lower()
    if swo:
        pool = [o for o in pool if (o.get('name') or '').lower() >= swo]
    nlt = (q.get('namelessthan') or '').lower()
    if nlt:
        pool = [o for o in pool if (o.get('name') or '').lower() < nlt]
    years = {int(y) for y in csv(q.get('years')) if y.isdigit()}
    if years:
        pool = [o for o in pool if o.get('year') in years]
    genres = {g.lower() for g in csv(q.get('genres'))} | {g.lower() for g in (q.get('genres') or '').split('|') if g}
    if genres:
        pool = [o for o in pool if genres & {g.lower() for g in o.get('genres', [])}]
    sort = [s.lower() for s in csv(q.get('sortby'))] or (['indexnumber'] if parent and items.get(parent, {}).get('type') in ('Season', 'Series', 'MusicAlbum') else ['sortname'])
    desc = (q.get('sortorder') or '').lower().startswith('desc')
    if 'random' in sort:
        import random
        random.shuffle(pool)
    else:
        for s in reversed(sort):
            if s == 'dateplayed':
                prog = state[0]
                pool.sort(key=lambda o: prog.get(o.get('mid'), (0, 0, 0, 0))[2], reverse=desc)
            elif s in SORTS:
                pool.sort(key=SORTS[s], reverse=desc)
    return pool


def page(h, cat, pool, q, state, sid):
    total = len(pool)
    try:
        start = max(0, int(q.get('startindex') or 0))
    except ValueError:
        start = 0
    try:
        limit = int(q.get('limit')) if q.get('limit') else None
    except ValueError:
        limit = None
    chunk = pool[start:start + limit] if limit is not None else pool[start:]
    return J(h, {'Items': [dto(cat, o, state, sid) for o in chunk], 'TotalRecordCount': total, 'StartIndex': start})


def resume_list(cat, state, q):
    prog = state[0]
    out = []
    for mid, (pos, dur, upd, done) in prog.items():
        if done or pos <= 0:
            continue
        o = cat['items'].get(media_of(mid))
        if not o:
            continue
        if (o.get('duration') or dur) and pos >= (o.get('duration') or dur) * 0.9:
            continue
        mt = {t.lower() for t in csv(q.get('mediatypes'))}
        if mt and ('audio' if o['kind'] == 'audio' else 'video') not in mt:
            continue
        pid = norm_id(q.get('parentid', ''))
        if pid and cat['items'].get(pid, {}).get('type') == 'CollectionFolder' and o['lib'] != cat['items'][pid]['lib']:
            continue
        out.append((upd, o))
    out.sort(key=lambda x: -x[0])
    return [o for _, o in out]


def next_up(cat, state, q):
    prog = state[0]
    want = norm_id(q.get('seriesid', ''))
    out = []
    for o in cat['items'].values():
        if o['type'] != 'Series' or (want and o['jid'] != want):
            continue
        eps = leaf_ids(cat, o)
        last_i, last_t = -1, 0
        for i, e in enumerate(eps):
            p = prog.get(cat['items'][e]['mid'])
            if p and (p[3] or p[0] > 0) and p[2] >= last_t:
                last_i, last_t = i, p[2]
        if last_i < 0:
            continue
        for e in eps[last_i:]:
            p = prog.get(cat['items'][e]['mid'])
            if not (p and p[3]):
                out.append((last_t, cat['items'][e])); break
    out.sort(key=lambda x: -x[0])
    return [o for _, o in out]


# ---------------------------------------------------------------- Dateien
def send_file(h, f, mime, cache='no-store'):
    """Datei mit Range-Unterstützung senden (für Video/Audio/Bilder)."""
    try:
        base = S.MEDIA.resolve()
        rf = Path(f).resolve(strict=True)
        meta_dir = (S.DATA / 'meta').resolve()
        if base not in rf.parents and meta_dir not in rf.parents:  # Medien oder heruntergeladene Metadaten-Bilder
            return h.send(403, b'{"error":"FORBIDDEN"}')
        st = rf.stat()
        size = st.st_size
        start, end = 0, size - 1
        rng = h.headers.get('Range', '')
        if rng:
            m = re.fullmatch(r'bytes=(\d*)-(\d*)', rng.strip())
            if not m or (not m.group(1) and not m.group(2)):
                return h.send(416, b'', 'text/plain', {'Content-Range': 'bytes */%d' % size})
            a, b = m.groups()
            if a:
                start = int(a)
                if b:
                    end = min(end, int(b))
            else:
                start = max(0, size - int(b))
            if start >= size or end < start:
                return h.send(416, b'', 'text/plain', {'Content-Range': 'bytes */%d' % size})
        fd = os.open(str(rf), os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                return h.send(403, b'{"error":"FORBIDDEN"}')
            length = end - start + 1
            h.send_response(206 if rng else 200)
            h.send_header('Content-Type', mime)
            h.send_header('Accept-Ranges', 'bytes')
            h.send_header('Content-Length', str(length))
            if rng:
                h.send_header('Content-Range', 'bytes %d-%d/%d' % (start, end, size))
            h.send_header('Cache-Control', cache)
            h.send_header('X-Content-Type-Options', 'nosniff')
            for k, v in (getattr(h, '_extra_headers', None) or {}).items():
                h.send_header(k, v)
            h._extra_headers = None
            h.end_headers()
            if h.command == 'HEAD':
                return
            with os.fdopen(fd, 'rb') as stream:
                fd = -1
                stream.seek(start)
                while length > 0:
                    buf = stream.read(min(262144, length))
                    if not buf:
                        break
                    h.wfile.write(buf); length -= len(buf)
        finally:
            if fd >= 0:
                os.close(fd)
    except (OSError, BrokenPipeError, ConnectionResetError):
        pass


WEB = None


def serve_web(h, rel):
    rel = urllib.parse.unquote(rel or 'index.html')
    if rel in ('', '/'):
        rel = 'index.html'
    root = (S.ROOT / 'jfweb').resolve()
    own = rel.startswith('bmc/')
    if own:
        root = (S.ROOT / 'bmcweb').resolve(); rel = rel[4:]
    try:
        f = (root / rel).resolve(strict=True)
        if root not in f.parents or not f.is_file():
            raise OSError
    except OSError:
        return h.send(404, b'{"error":"NOT_FOUND"}')
    mime = mimetypes.guess_type(f.name)[0] or 'application/octet-stream'
    if f.suffix == '.js':
        mime = 'text/javascript; charset=utf-8'
    elif f.suffix in ('.html', '.css', '.json', '.txt'):
        mime = (mime or 'text/plain') + '; charset=utf-8'
    elif f.suffix == '.woff2':
        mime = 'font/woff2'
    elif f.suffix == '.wasm':
        mime = 'application/wasm'
    hashed = bool(re.search(r'\.[0-9a-f]{16,}\.', f.name))
    cache = 'public, max-age=31536000, immutable' if hashed else 'no-cache'
    data = f.read_bytes()
    if rel == 'index.html' and not own:
        # Butchies-Player-Aussehen einbinden (eigene Dateien unter /web/bmc/)
        try:
            v = '%x' % int(max(x.stat().st_mtime for x in (S.ROOT / 'bmcweb').iterdir()))
        except (OSError, ValueError):
            v = '0'
        inj = ('<link rel="stylesheet" href="bmc/bmc-artwork.css?v=%s">'
               '<link rel="stylesheet" href="bmc/bmc-cardsize.css?v=%s">'
               '<script defer src="bmc/bmc-artwork.js?v=%s"></script>'
               '<script defer src="bmc/bmc-cardsize.js?v=%s"></script>'
               '<script defer src="bmc/bmc-core.js?v=%s"></script>') % (v, v, v, v, v)
        if player_look():  # Detailseite im gewohnten Aufbau gehört zum Butchies-Aussehen
            inj += '<link rel="stylesheet" href="bmc/bmc-detail.css?v=%s"><script defer src="bmc/bmc-detail.js?v=%s"></script>' % (v, v)
            inj += '<link rel="stylesheet" href="bmc/bmc-moviedetail.css?v=%s"><script defer src="bmc/bmc-moviedetail.js?v=%s"></script>' % (v, v)
            inj += '<link rel="stylesheet" href="bmc/bmc-shell.css?v=%s"><script defer src="bmc/bmc-shell.js?v=%s"></script>' % (v, v)
        if player_look():  # Butchies-Player nur, wenn unter Dashboard → Plugins eingeschaltet
            inj += '<link rel="stylesheet" href="bmc/bmc-player.css?v=%s"><script defer src="bmc/bmc-player.js?v=%s"></script>' % (v, v)
        inj = (inj + '</head>').encode()
        data = data.replace(b'</head>', inj, 1)
    etag = '"%x-%x%s"' % (int(f.stat().st_mtime), len(data), 'p' if rel == 'index.html' and player_look() else '')
    if h.headers.get('If-None-Match') == etag:
        h.send_response(304); h.send_header('ETag', etag); h.end_headers(); return
    hdr = {'Cache-Control': cache, 'ETag': etag, 'X-Frame-Options': 'SAMEORIGIN'}
    if own and rel.startswith('player/'):
        # Butchies-Player: „cross-origin isolated“, damit der Decoder mehrere Prozessorkerne nutzen darf
        hdr.update({'Cross-Origin-Opener-Policy': 'same-origin', 'Cross-Origin-Embedder-Policy': 'require-corp',
                    'Cross-Origin-Resource-Policy': 'same-origin'})
    return h.send(200, data, mime, hdr)


# ---------------------------------------------------------------- Schalter „Butchies-Player“ (als Plugin)
PLAYER_PLUGIN_ID = 'b7c4e0d2a91f4b3c8e6d5a4f3b2c1d0e'
HELPER_PLUGIN_ID = 'c3d9e1f5a7b24c6d8e0f1a2b3c4d5e6f'
PLAYER_PLUGIN_VER = '1.0.0'


def _settings_file():
    return S.DATA / 'jf_settings.json'


def jf_settings():
    try:
        return json.loads(_settings_file().read_text('utf-8'))
    except (OSError, ValueError):
        return {}


def save_setting(key, value):
    cfg = jf_settings(); cfg[key] = value
    tmp = _settings_file().with_suffix('.tmp')
    tmp.write_text(json.dumps(cfg), 'utf-8'); os.replace(str(tmp), str(_settings_file()))


def branding():
    """Dashboard → Allgemein → Branding (eigenes CSS = Jellyfin-Designs/Themes, Login-Hinweis)."""
    b = jf_settings().get('branding') or {}
    return {'LoginDisclaimer': str(b.get('LoginDisclaimer') or ''), 'CustomCss': str(b.get('CustomCss') or ''),
            'SplashscreenEnabled': bool(b.get('SplashscreenEnabled', False))}


def save_branding(data):
    cur = branding()
    for k in cur:
        if k in data and data[k] is not None:
            cur[k] = bool(data[k]) if k == 'SplashscreenEnabled' else str(data[k])[:200000]
    save_setting('branding', cur)


def x265_helper():
    """Aus (Standard) = reiner Direkt-Stream: das NAS gibt die Originaldatei nur weiter, nichts wird umgepackt
    oder umgerechnet, kein Ersatz-Player. An = Umpacken (Ton → AAC) + Butchies-Web-Player, wenn der Browser es nicht kann."""
    return bool(jf_settings().get('x265_helper', False))


def player_look():
    return True  # Nutzerwunsch 18.11.2026: Butchies-Player-Aussehen ist Standard, kein Plugin mehr


TMDB_PLUGIN_ID = 'a8f1c3e5b7d94f2e9c0b1a2d3e4f5a6b'


def plugins_list():
    return [{'Name': 'TMDb-Metadaten', 'Version': '1.0.0', 'ConfigurationFileName': 'tmdb.json',
             'Description': 'Lädt Filmplakate, Hintergrundbilder, Logos, Beschreibungen, Genres und Schauspieler von '
                            'themoviedb.org. Braucht einen eigenen kostenlosen API-Schlüssel (Einstellungen). '
                            'Eigene .nfo-Dateien und Bilder neben den Filmen haben immer Vorrang.',
             'Id': TMDB_PLUGIN_ID, 'CanUninstall': False, 'HasImage': False,
             'Status': 'Active' if jf_meta.tmdb_on() else 'Disabled'},
            {'Name': 'Browser-Hilfe (x265/Kino-Ton)', 'Version': '1.0.0', 'ConfigurationFileName': None,
             'Description': 'Ausgeschaltet (Standard) = reiner Direkt-Stream: das NAS gibt jeden Film unverändert weiter, '
                            'abgespielt wird nur auf deinem Gerät (Apps, Moonfin, Edge/Chrome). '
                            'Eingeschaltet = für Browser, die einen Film nicht können: Ton wird umgepackt bzw. der '
                            'Butchies-Web-Player springt ein. Ein/aus über „Einstellungen“.',
             'Id': HELPER_PLUGIN_ID, 'CanUninstall': False, 'HasImage': False,
             'Status': 'Active' if x265_helper() else 'Disabled'}]


def switch_pages():
    return {
        HELPER_PLUGIN_ID: ('Browser-Hilfe', 'x265_helper', 'Browser-Hilfe (x265/Kino-Ton)',
                           'Ausgeschaltet = reiner Direkt-Stream: das NAS gibt jeden Film unverändert weiter. '
                           'Eingeschaltet = für Browser, die einen Film nicht können (z. B. Firefox bei DTS/AC3-Ton): '
                           'das Bild bleibt original, nur der Ton wird in AAC-Stereo umgepackt; kann der Browser das Bild '
                           '(x265) gar nicht, springt der Butchies-Web-Player ein. Apps, die alles können, bekommen weiter die Originaldatei.',
                           'Browser-Hilfe einschalten', 'Den Film danach neu starten.'),
    }


def plugin_route(h, method, p):
    m = re.fullmatch(r'/plugins/([0-9a-f-]{32,36})(?:/([^/]+))?(?:/(enable|disable|image|configuration|manifest))?', p)
    if m and norm_id(m.group(1)) == TMDB_PLUGIN_ID:
        act = m.group(3) or (m.group(2) or '')
        if act == 'configuration':
            if method == 'POST':
                d = body_json(h)
                cfg = jf_meta.settings()
                key = str(d.get('ApiKey') or '').strip()
                if key.startswith('•'):
                    key = cfg['ApiKey']  # unverändert (nur die Maske kam zurück)
                if key and not re.fullmatch(r'[A-Za-z0-9._-]{16,400}', key):
                    return J(h, {'error': 'Schlüssel sieht nicht richtig aus.'}, 400)
                cfg.update(ApiKey=key, Enabled=bool(d.get('Enabled', True)),
                           Language=str(d.get('Language') or 'de-DE')[:8], Country=str(d.get('Country') or 'DE')[:2].upper())
                save_setting('tmdb', cfg)
                jf_meta._ctx = None
                jf_meta.wake()
                return none(h)
            cfg = dict(jf_meta.settings())
            cfg['ApiKey'] = ('•' * 8 + cfg['ApiKey'][-4:]) if cfg['ApiKey'] else ''
            cfg['HasKey'] = bool(jf_meta.settings()['ApiKey'])
            cfg['Status'] = jf_meta.status()
            return J(h, cfg)
        if act in ('enable', 'disable') and method == 'POST':
            cfg = jf_meta.settings(); cfg['Enabled'] = act == 'enable'; save_setting('tmdb', cfg); jf_meta.wake()
            return none(h)
        if act == 'refresh' and method == 'POST':
            with S.sqlite_session(S.DATA / 'library.sqlite') as c:
                c.execute("UPDATE jf_meta SET tmdb_status='off'")
            jf_meta.wake(); return none(h)
        return h.send(404, b'', 'text/plain', {})
    if m and norm_id(m.group(1)) in switch_pages():
        key = switch_pages()[norm_id(m.group(1))][1]
        act = m.group(3) or (m.group(2) if m.group(2) in ('enable', 'disable', 'configuration') else '')
        if act in ('enable', 'disable') and method == 'POST':
            save_setting(key, act == 'enable'); return none(h)
        if act == '' and method == 'DELETE':
            save_setting(key, False); return none(h)
        if act == 'configuration':
            if method == 'POST':
                save_setting(key, bool(body_json(h).get('Enabled'))); return none(h)
            return J(h, {'Enabled': bool(jf_settings().get(key, False))})
        return h.send(404, b'', 'text/plain', {})
    if not m or norm_id(m.group(1)) != PLAYER_PLUGIN_ID:
        return None
    act = m.group(3) or ('' if not m.group(2) else m.group(2) if m.group(2) in ('enable', 'disable', 'image', 'configuration') else '')
    if act in ('enable', 'disable') and method == 'POST':
        save_setting('butchies_player', act == 'enable')
        return none(h)
    if act == 'configuration':
        return J(h, {})
    if act == '' and method == 'DELETE':  # „Deinstallieren“ = ausschalten (Plugin ist fest eingebaut)
        save_setting('butchies_player', False)
        return none(h)
    return h.send(404, b'', 'text/plain', {})


# ---------------------------------------------------------------- Ersteinrichtung (Jellyfin-Assistent)
def wizard_active():
    return not jf_settings().get('wizard_done')


def local_client(h):
    import ipaddress
    try:
        if S.via_proxy(h):
            return False  # über den Internet-Proxy -> nie „Heimnetz“
        ip = ipaddress.ip_address(h.client_address[0])
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except (ValueError, IndexError, TypeError):
        return False


SETUP_PATHS = ('/library/virtualfolders', '/environment/', '/libraries/availableoptions', '/library/physicalpaths')


def startup(h, method, p):
    """/Startup/* – nur solange die Einrichtung offen ist und nur aus dem Heimnetz."""
    if not wizard_active() or not local_client(h):
        return J(h, {'error': 'SETUP_COMPLETE'}, 401)
    if p == '/startup/configuration':
        if method == 'POST':
            d = body_json(h)
            cfg = jf_meta.settings()
            lang = str(d.get('PreferredMetadataLanguage') or 'de')[:2].lower()
            country = str(d.get('MetadataCountryCode') or 'DE')[:2].upper()
            cfg.update(Language='%s-%s' % (lang, country), Country=country)
            save_setting('tmdb', cfg)
            return none(h)
        return J(h, {'UICulture': 'de', 'MetadataCountryCode': 'DE', 'PreferredMetadataLanguage': 'de'})
    if p in ('/startup/user', '/startup/firstuser'):
        if method == 'POST':
            d = body_json(h)
            name, pw = str(d.get('Name') or '').strip(), str(d.get('Password') or '')
            if S.accounts.count():
                return none(h)  # schon angelegt (Zurück-Knopf im Assistenten)
            try:
                S.accounts.register_first_admin(name, pw)
            except ValueError:
                return h.send(400, 'Name: 3–32 Zeichen (Buchstaben, Zahlen, - oder _), Passwort mindestens 6 Zeichen.'.encode(),
                              'text/plain; charset=utf-8', {})
            try:
                S.clear_setup_code()
            except Exception:
                pass
            return none(h)
        u = S.accounts.list_users()
        return J(h, {'Name': u[0]['name'] if u else 'admin', 'Password': ''})
    if p == '/startup/remoteaccess':
        body_json(h); return none(h)
    if p == '/startup/complete' and method == 'POST':
        if not S.accounts.count():
            return J(h, {'error': 'Bitte zuerst ein Administratorkonto anlegen.'}, 400)
        save_setting('wizard_done', True)
        return none(h)
    return J(h, {'error': 'NOT_FOUND'}, 404)


# ---------------------------------------------------------------- Hauptweiche
def handle(h, method):
    """True, wenn die Anfrage hier beantwortet wurde."""
    u = urllib.parse.urlsplit(h.path)
    path = u.path
    # optionales Präfix /emby oder /jellyfin (manche Apps)
    for pre in ('/emby/', '/mediabrowser/', '/jellyfin/'):
        if path.lower().startswith(pre):
            path = path[len(pre) - 1:]
    p = path.lower().rstrip('/') or '/'
    if p == '/' and method in ('GET', 'HEAD'):
        h.send(302, b'', 'text/plain', {'Location': '/web/'}); return True
    if path == '/web' or path.lower() == '/web/index.html' and False:
        h.send(302, b'', 'text/plain', {'Location': '/web/'}); return True
    if path.lower().startswith('/web/') and method in ('GET', 'HEAD') and not p.startswith('/web/configurationpage'):
        serve_web(h, path[5:]); return True
    try:
        r = route(h, method, path, p)
    except (BrokenPipeError, ConnectionResetError):
        return True
    if r is False:
        return False
    return True


def route(h, method, path, p):
    sid = server_id()
    q = qparams(h)
    parts = path.strip('/').split('/')
    lp = [x.lower() for x in parts]

    # ---------- öffentlich
    if p in ('/system/info/public', '/system/info'):
        user = current_user(h)
        if S.via_proxy(h) and h.headers.get('X-Forwarded-Host'):  # über die Tür von unterwegs: öffentliche Adresse melden
            local_addr = 'https://' + h.headers.get('X-Forwarded-Host').split(',')[0].strip()
        else:
            local_addr = ('https' if S.TLS_CERT and S.TLS_KEY else 'http') + '://' + (h.headers.get('Host') or '')
        info = {'LocalAddress': local_addr,
                'ServerName': PRODUCT, 'Version': SERVER_VERSION, 'ProductName': 'Jellyfin Server', 'OperatingSystem': 'Linux',
                'Id': sid, 'StartupWizardCompleted': not wizard_active()}
        if p == '/system/info':
            if not user:
                return J(h, {'error': 'AUTH_REQUIRED'}, 401)
            info.update(OperatingSystemDisplayName='WD My Cloud', HasPendingRestart=False, IsShuttingDown=False,
                        SupportsLibraryMonitor=False, WebSocketPortNumber=0, CompletedInstallations=[], CanSelfRestart=False,
                        CanLaunchWebBrowser=False, ProgramDataPath='', WebPath='', ItemsByNamePath='', CachePath='', LogPath='',
                        InternalMetadataPath='', TranscodingTempPath='', CastReceiverApplications=[], HasUpdateAvailable=False,
                        EncoderLocation='System', SystemArchitecture='Arm')
        return J(h, info)
    if p == '/system/ping':
        return J(h, PRODUCT)
    if p == '/system/endpoint':
        return J(h, {'IsLocal': True, 'IsInNetwork': True})
    if p == '/branding/configuration':
        return J(h, branding())
    if p in ('/branding/css', '/branding/css.css'):
        h.send(200, branding()['CustomCss'].encode('utf-8'), 'text/css; charset=utf-8', {'Cache-Control': 'no-cache'}); return True
    if p == '/users/public':
        return J(h, [])
    if p == '/quickconnect/enabled':
        return J(h, False)
    if p == '/users/authenticatebyname' and method == 'POST':
        return login(h, sid)
    if p.startswith('/startup/'):
        return startup(h, method, p)
    if p == '/socket':
        u = current_user(h)
        if not u:
            return J(h, {'error': 'AUTH_REQUIRED'}, 401)
        return jf_ws.serve(h, u[0])
    if p.startswith('/localization/'):
        return localization(h, p)
    if p == '/fallbackfont/fonts':
        return J(h, [])
    if p == '/web/configurationpage':
        sw = next(((i, v) for i, v in switch_pages().items() if v[0] == (q.get('name') or '')), None)
        if sw:
            esc = lambda t: t.replace('&', '&amp;').replace('<', '&lt;')
            html = (S.ROOT / 'bmcweb' / 'switch-config.html').read_text('utf-8')
            for k, v in (('@@ID@@', sw[0]), ('@@TITLE@@', esc(sw[1][2])), ('@@TEXT@@', esc(sw[1][3])),
                         ('@@LABEL@@', esc(sw[1][4])), ('@@AFTER@@', esc(sw[1][5]))):
                html = html.replace(k, v)
            return h.send(200, html.encode('utf-8'), 'text/html; charset=utf-8', {'Cache-Control': 'no-cache'})
        if (q.get('name') or '') != 'TMDb-Metadaten':
            return h.send(404, b'', 'text/plain', {})
        return h.send(200, (S.ROOT / 'bmcweb' / 'tmdb-config.html').read_bytes(), 'text/html; charset=utf-8', {'Cache-Control': 'no-cache'})

    # ---------- ab hier angemeldet
    user = current_user(h)
    if not user and wizard_active() and local_client(h) and p.startswith(SETUP_PATHS):
        user = (0, 'einrichtung', 'admin')  # Bibliotheken im Einrichtungs-Assistenten anlegen
    if not user:
        if p.startswith(('/videos/', '/audio/', '/items/')) and '/images/' in p:
            pass  # Bilder dürfen ohne Anmeldung (tragen keine geheimen Daten)
        else:
            return J(h, {'error': 'AUTH_REQUIRED'}, 401) if is_api(p) else False
    if user:
        jf_sessions.touch(h, user)
        import jf_admin
        r = jf_admin.route(h, method, path, p, q, user, sid)
        if r is not None:
            return True
    cat = jf_playlists.with_playlists(catalog(), user)
    state = user_state(user[0], user) if user else ({}, set())
    if user and (p in ('/playlists', '/collections') or p.startswith(('/playlists/', '/collections/'))):
        r = jf_playlists.route(h, method, p, q, user, cat, state, sid)
        if r is not None:
            return r

    if p == '/sessions/logout' and method == 'POST':
        S.accounts.logout(auth_token(h)); return none(h)
    if p in ('/users/me',) or (len(lp) == 2 and lp[0] == 'users' and norm_id(lp[1]) and method == 'GET'):
        return J(h, user_dto(user, sid))
    if p == '/users' and method == 'GET':
        if user[2] != 'admin':
            return J(h, [user_dto(user, sid)])
        return J(h, [user_dto((u['id'], u['name'], u['role']), sid) for u in S.accounts.list_users()])
    if p == '/users/configuration' or (len(lp) == 3 and lp[0] == 'users' and lp[2] == 'configuration'):
        if method == 'POST':
            cfg = body_json(h)
            with S.sqlite_session(S.DATA / 'library.sqlite') as c:
                c.execute('INSERT OR REPLACE INTO jf_userconfig(user_id,payload) VALUES(?,?)', (user[0], json.dumps(cfg)[:20000]))
            return none(h)
    if lp[0] == 'displaypreferences' and len(lp) == 2:
        return display_prefs(h, method, user, lp[1], q)
    if p in ('/userviews',) or (len(lp) == 3 and lp[0] == 'users' and lp[2] == 'views'):
        views = [cat['items'][i] for i in cat['libs']]
        return J(h, {'Items': [dto(cat, o, state, sid) for o in views], 'TotalRecordCount': len(views), 'StartIndex': 0})
    if p == '/userviews/groupingoptions' or (len(lp) == 4 and lp[2] == 'groupingoptions'):
        return J(h, [{'Name': cat['items'][i]['name'], 'Id': i} for i in cat['libs']])
    if p in ('/useritems/resume', '/items/resume') or (len(lp) == 4 and lp[0] == 'users' and lp[2] == 'items' and lp[3] == 'resume'):
        return page(h, cat, resume_list(cat, state, q), q, state, sid)
    if p in ('/items/latest',) or (len(lp) == 4 and lp[0] == 'users' and lp[2] == 'items' and lp[3] == 'latest'):
        return latest(h, cat, state, q, sid)
    if p == '/shows/nextup':
        return page(h, cat, next_up(cat, state, q), q, state, sid)
    if p == '/shows/upcoming':
        return J(h, {'Items': [], 'TotalRecordCount': 0, 'StartIndex': 0})
    if len(lp) == 3 and lp[0] == 'shows' and lp[2] in ('seasons', 'episodes'):
        sid_ = norm_id(lp[1]); ser = cat['items'].get(sid_)
        if not ser:
            return J(h, {'Items': [], 'TotalRecordCount': 0, 'StartIndex': 0})
        if lp[2] == 'seasons':
            pool = [cat['items'][z] for z in ser['children']]
        else:
            season = norm_id(q.get('seasonid', ''))
            pool = [cat['items'][e] for e in (cat['items'][season]['children'] if season in cat['items'] else leaf_ids(cat, ser))]
        return page(h, cat, pool, q, state, sid)
    if p in ('/items', '/users/%s/items' % (lp[1] if len(lp) > 1 else '')) and method == 'GET':
        return page(h, cat, query_items(cat, q, user, state), q, state, sid)
    if p == '/items/filters' or p == '/items/filters2':
        pool = query_items(cat, q, user, state)
        gs = sorted({g for o in pool for g in o.get('genres', [])})
        ys = sorted({o['year'] for o in pool if o.get('year')}, reverse=True)
        if p.endswith('2'):
            return J(h, {'Genres': [{'Name': g, 'Id': _h('genre', g) + '00'} for g in gs], 'Tags': []})
        return J(h, {'Genres': gs, 'Tags': [], 'OfficialRatings': [], 'Years': ys})
    if p == '/items/counts':
        its = cat['items'].values()
        cnt = lambda t: sum(1 for o in its if o['type'] == t)
        return J(h, {'MovieCount': cnt('Movie'), 'SeriesCount': cnt('Series'), 'EpisodeCount': cnt('Episode'), 'SongCount': cnt('Audio'),
                     'AlbumCount': cnt('MusicAlbum'), 'ArtistCount': sum(1 for a in cat.get('people', {}).values() if a['type'] == 'MusicArtist'), 'ProgramCount': 0, 'TrailerCount': 0, 'MusicVideoCount': 0,
                     'BoxSetCount': 0, 'BookCount': 0, 'ItemCount': len(cat['items'])})
    m = re.fullmatch(r'/artists/([^/]+)', p)
    if m and m.group(1) != 'albumartists':
        name = urllib.parse.unquote(path.split('/')[-1]).lower()
        a = next((x for x in cat.get('people', {}).values() if x['type'] == 'MusicArtist' and x['name'].lower() == name), None)
        return J(h, dto(cat, a, state, sid, full=True)) if a else J(h, {'error': 'NOT_FOUND'}, 404)
    if p in ('/genres', '/musicgenres', '/studios', '/persons', '/artists', '/artists/albumartists'):
        if p in ('/artists', '/artists/albumartists'):
            lib = cat['items'].get(norm_id(q.get('parentid', '')), {}).get('lib')
            ars = [a for a in cat.get('people', {}).values() if a['type'] == 'MusicArtist' and (lib is None or a['lib'] == lib)]
            term = (q.get('searchterm') or '').strip().lower()
            if term:
                ars = [a for a in ars if term in a['name'].lower()]
            ars.sort(key=lambda a: a['name'].lower())
            start = int(q.get('startindex') or 0); lim = int(q.get('limit') or 0) or len(ars)
            return J(h, {'Items': [dto(cat, a, state, sid) for a in ars[start:start + lim]], 'TotalRecordCount': len(ars), 'StartIndex': start})
        if p == '/genres':
            gs = sorted({g for o in query_items(cat, q, user, state) for g in o.get('genres', [])})
            return J(h, {'Items': [{'Name': g, 'Id': _h('genre', g) + '00', 'Type': 'Genre', 'ServerId': sid, 'ImageTags': {}} for g in gs],
                         'TotalRecordCount': len(gs), 'StartIndex': 0})
        return J(h, {'Items': [], 'TotalRecordCount': 0, 'StartIndex': 0})
    if p == '/search/hints':
        q2 = dict(q); q2['recursive'] = 'true'
        pool = query_items(cat, q2, user, state)[:int(q.get('limit') or 30)]
        hints = [{'ItemId': o['jid'], 'Id': o['jid'], 'Name': o['name'], 'Type': o['type'], 'MediaType': 'Video' if o.get('kind') == 'video' else ('Audio' if o.get('kind') == 'audio' else None),
                  'PrimaryImageTag': o.get('cover_tag'), 'ProductionYear': o.get('year'), 'IsFolder': bool(o.get('folder'))} for o in pool]
        return J(h, {'SearchHints': hints, 'TotalRecordCount': len(hints)})

    # Favoriten / Gesehen
    m = re.fullmatch(r'/(?:users/[0-9a-f-]+/)?(favoriteitems|userfavoriteitems|playeditems|userplayeditems)/([0-9a-f-]+)', p)
    if m and method in ('POST', 'DELETE'):
        iid = norm_id(m.group(2)); o = cat['items'].get(iid)
        if not o:
            return J(h, {'error': 'NOT_FOUND'}, 404)
        on = method == 'POST'
        if 'favorite' in m.group(1):
            with S.sqlite_session(S.DATA / 'library.sqlite') as c:
                if on:
                    c.execute('INSERT OR IGNORE INTO jf_favorites(user_id,item_id) VALUES(?,?)', (user[0], iid))
                else:
                    c.execute('DELETE FROM jf_favorites WHERE user_id=? AND item_id=?', (user[0], iid))
        else:
            now = int(time.time())
            with S.sqlite_session(S.DATA / 'library.sqlite') as c:
                for leaf in leaf_ids(cat, o):
                    mid = cat['items'][leaf]['mid']
                    if on:
                        c.execute('INSERT INTO playback_progress(user_id,media_id,position,duration,updated,completed) VALUES(?,?,0,0,?,1) '
                                  'ON CONFLICT(user_id,media_id) DO UPDATE SET position=0,completed=1,updated=excluded.updated', (user[0], mid, now))
                    else:
                        c.execute('DELETE FROM playback_progress WHERE user_id=? AND media_id=?', (user[0], mid))
        notify_userdata(cat, user[0], [iid])
        return J(h, user_data(cat, o, user_state(user[0])))
    m = re.fullmatch(r'/(?:users/[0-9a-f-]+/items|useritems)/([0-9a-f-]+)/userdata', p)
    if m:
        o = cat['items'].get(norm_id(m.group(1)))
        return J(h, user_data(cat, o, state)) if o else J(h, {'error': 'NOT_FOUND'}, 404)

    # Identifizieren (TMDB-Suche) – nur Admin
    m = re.fullmatch(r'/items/remotesearch/(movie|series|apply/([0-9a-f-]{32,36}))', p)
    if m and method == 'POST':
        if user[2] != 'admin':
            return J(h, {'error': 'FORBIDDEN'}, 403)
        d = body_json(h)
        if m.group(2):
            o = cat['items'].get(norm_id(m.group(2)))
            tid = str((d.get('ProviderIds') or {}).get('Tmdb') or '')
            if not o or o['type'] not in ('Movie', 'Series') or not tid.isdigit():
                return J(h, {'error': 'NOT_FOUND'}, 404)
            try:
                jf_meta.identify(*meta_target(cat, o), tid)
            except jf_meta.TmdbError as e:
                return h.send(502, str(e).encode(), 'text/plain; charset=utf-8', {})
            return none(h)
        if not jf_meta.tmdb_on():
            return J(h, [])
        info = d.get('SearchInfo') or {}
        ids = {k.lower(): str(v) for k, v in (info.get('ProviderIds') or {}).items() if v}
        try:
            return J(h, jf_meta.search('series' if m.group(1) == 'series' else 'movie', str(info.get('Name') or '').strip(),
                                       info.get('Year'), ids))
        except jf_meta.TmdbError as e:
            return h.send(502, str(e).encode(), 'text/plain; charset=utf-8', {})

    # Einzelnes Element + Zubehör
    m = re.fullmatch(r'/(?:users/[0-9a-f-]+/)?items/([0-9a-f-]{32,36})(?:/(.*))?', p)
    if m:
        iid = norm_id(m.group(1)); rest = m.group(2) or ''
        o = cat['items'].get(iid) or cat.get('people', {}).get(iid)
        if rest == 'refresh' and method == 'POST':
            if user[2] != 'admin':
                return J(h, {'error': 'FORBIDDEN'}, 403)
            keys = []
            for x in [o] + [cat['items'][j] for j in (leaf_ids(cat, o) if o and o.get('folder') else [])]:
                if x:
                    keys.append(x.get('mid') or x['jid'])
            eds = jf_meta.load_edits()
            if str(q.get('replaceallimages', '')).lower() == 'true':  # „Alle Bilder ersetzen“: eigene Bildauswahl zurücksetzen
                for k in keys:
                    for lst in ((eds.get(k) or {}).get('images') or {}).values():
                        for pth in lst if isinstance(lst, list) else []:
                            if jf_images._own_copy(pth):
                                try:
                                    os.unlink(pth)
                                except OSError:
                                    pass
                    jf_meta.drop_edit(k, ['images'])
                invalidate()
            jf_meta.forget([k for k in keys if not (eds.get(k) or {}).get('lock_data')])  # gesperrte Einträge bleiben
            return none(h)
        if rest.startswith(('images', 'remoteimages')):
            r = jf_images.route(h, method, cat, o, rest, q, user)
            if r is not None:
                return True
            return image(h, cat, o, rest)
        if not o:
            return J(h, {'error': 'NOT_FOUND'}, 404)
        if rest == '' and method == 'GET':
            return J(h, dto(cat, o, state, sid, full=True))
        if rest == '' and method == 'DELETE' and o and o['type'] in ('Playlist', 'BoxSet'):
            return none(h) if jf_playlists.delete(user, iid) else J(h, {'error': 'NOT_FOUND'}, 404)
        if rest == '' and method == 'POST':
            if user[2] != 'admin':
                return J(h, {'error': 'FORBIDDEN'}, 403)
            return save_item_edit(h, cat, o, body_json(h))
        if rest == 'externalidinfos':
            t = 'Series' if o['type'] == 'Series' else 'Movie'
            return J(h, [{'Name': 'TheMovieDb', 'Key': 'Tmdb', 'Type': t, 'UrlFormatString': 'https://www.themoviedb.org/%s/{0}' % ('tv' if t == 'Series' else 'movie')},
                         {'Name': 'IMDb', 'Key': 'Imdb', 'Type': t, 'UrlFormatString': 'https://www.imdb.com/title/{0}'},
                         {'Name': 'TheTVDB', 'Key': 'Tvdb', 'Type': t, 'UrlFormatString': 'https://www.thetvdb.com/?tab=%s&id={0}' % ('series' if t == 'Series' else 'movie')}])
        if rest == 'metadataeditor':
            ratings = ['FSK-0', 'FSK-6', 'FSK-12', 'FSK-16', 'FSK-18']
            return J(h, {'ParentalRatingOptions': [{'Name': r, 'Value': i * 6} for i, r in enumerate(ratings)],
                         'Countries': [{'Name': 'DE', 'DisplayName': 'Deutschland', 'TwoLetterISORegionName': 'DE', 'ThreeLetterISORegionName': 'DEU'}],
                         'Cultures': [{'Name': 'German', 'DisplayName': 'Deutsch', 'TwoLetterISOLanguageName': 'de', 'ThreeLetterISOLanguageName': 'ger', 'ThreeLetterISOLanguageNames': ['ger']}],
                         'ExternalIdInfos': [], 'ContentType': None, 'ContentTypeOptions': []})
        if rest == 'playbackinfo':
            body = body_json(h) if method == 'POST' else {}
            if blocked(o):
                return J(h, {'MediaSources': [], 'PlaySessionId': secrets.token_hex(16), 'ErrorCode': 'NotAllowed'})
            psid = secrets.token_hex(16)
            ms = media_source(o, state, auth_token(h))
            prof = body.get('DeviceProfile') or {}
            try:
                aidx = int(q.get('audiostreamindex') if q.get('audiostreamindex') not in (None, '') else body.get('AudioStreamIndex'))
            except (TypeError, ValueError):
                aidx = None
            try:
                sticks = int(q.get('starttimeticks') or body.get('StartTimeTicks') or 0)
            except (TypeError, ValueError):
                sticks = 0
            helper = x265_helper()
            decision = play_decision(o, prof, aidx) if helper else 'direct'  # Standard: Originaldatei nur weitergeben
            vcodec = next((st.get('codec') for st in (o.get('streams') or []) if st['type'] == 'Video'), None)
            if helper and q.get('bmcnohevc') == '1' and vcodec == 'hevc' and decision != 'direct' and not _profile_ok(prof, 'mp4', 'hevc', 'aac'):
                decision = 'none'  # Browser kann sicher kein HEVC -> gleich den Butchies-Player nehmen
            if body.get('AllowVideoStreamCopy') is False or str(q.get('allowvideostreamcopy', '')).lower() == 'false':
                # Der Player will das Video umgerechnet haben (meist nach einem Abspielfehler). Das schafft das NAS nicht:
                # ehrlich „nicht kompatibel“ melden statt endlos neu zu versuchen.
                decision = 'none'
            try:
                sidx = int(q.get('subtitlestreamindex') if q.get('subtitlestreamindex') not in (None, '') else body.get('SubtitleStreamIndex'))
            except (TypeError, ValueError):
                sidx = None
            subs = [x['Index'] for x in ms['MediaStreams'] if x['Type'] == 'Subtitle']
            pa, ps = pick_tracks(ms['MediaStreams'], load_userconfig(user[0]))
            if aidx is None and pa is not None:
                ms['DefaultAudioStreamIndex'] = pa
            if sidx is None:  # nach den Wiedergabe-Einstellungen des Benutzers (Sprache, Untertitel-Modus)
                sidx = ps
            ms['DefaultSubtitleStreamIndex'] = sidx if sidx in subs else -1
            if q.get('bmcplayer') == '1':
                decision = 'direct'  # Butchies-Web-Player entschlüsselt selbst – braucht nur Spuren + Untertitel
            if decision == 'none':
                return J(h, {'MediaSources': [], 'PlaySessionId': psid, 'ErrorCode': 'NoCompatibleStream', 'BmcPlayer': helper})
            if decision == 'remux':
                ms.update(SupportsDirectPlay=False, SupportsDirectStream=False, SupportsTranscoding=True,
                          TranscodingContainer='mp4', TranscodingSubProtocol='http',
                          TranscodingUrl='/Videos/%s/stream.mp4?Static=false&MediaSourceId=%s&VideoCodec=copy&AudioCodec=aac'
                                         '&PlaySessionId=%s&api_key=%s%s%s' % (o['jid'], o['jid'], psid, urllib.parse.quote(auth_token(h)),
                                                                                '&AudioStreamIndex=%d' % aidx if aidx is not None else '',
                                                                                '&StartTimeTicks=%d' % sticks if sticks > 0 else ''))
            return J(h, {'MediaSources': [ms], 'PlaySessionId': psid, 'BmcHelper': helper})
        if rest in ('similar', 'instantmix'):
            pool = [x for x in cat['items'].values() if x['type'] == o['type'] and x['jid'] != o['jid'] and x['lib'] == o['lib']]
            import random
            random.shuffle(pool)
            if rest == 'similar':  # ähnlich = gleiche Genres, Schauspieler, Regie, Studios, Schlagwörter, Jahrzehnt
                g = set(o.get('genres') or []); pe = {x['Id'] for x in o.get('people') or []}
                st_ = set(o.get('studios') or []); tg = set(o.get('tags') or [])
                def score(x):
                    sc = 3 * len(g & set(x.get('genres') or [])) + 2 * len(pe & {y['Id'] for y in x.get('people') or []})
                    sc += len(st_ & set(x.get('studios') or [])) + len(tg & set(x.get('tags') or []))
                    if o.get('year') and x.get('year') and abs(o['year'] - x['year']) <= 5:
                        sc += 1
                    return sc
                pool.sort(key=score, reverse=True)
            return page(h, cat, pool, {'limit': q.get('limit') or '12'}, state, sid)
        if rest in ('localtrailers', 'specialfeatures'):
            return J(h, [])
        if rest == 'thememedia':
            empty = {'Items': [], 'TotalRecordCount': 0, 'StartIndex': 0, 'OwnerId': iid}
            return J(h, {'ThemeVideosResult': empty, 'ThemeSongsResult': empty, 'SoundtrackSongsResult': empty})
        if rest == 'intros':
            return J(h, {'Items': [], 'TotalRecordCount': 0, 'StartIndex': 0})
        if rest == 'ancestors':
            out = []; cur = o.get('parent')
            while cur and cur in cat['items']:
                out.append(dto(cat, cat['items'][cur], state, sid)); cur = cat['items'][cur].get('parent')
            return J(h, out)
        if rest == 'criticreviews':
            return J(h, {'Items': [], 'TotalRecordCount': 0, 'StartIndex': 0})
        if rest in ('download', 'file'):
            if o.get('folder'):
                return J(h, {'error': 'NOT_FOUND'}, 404)
            if not may_download(user):
                return J(h, {'error': 'FORBIDDEN'}, 403)
            name = Path(o['path']).name
            safe = re.sub(r'[^A-Za-z0-9._ -]', '_', name)
            h._extra_headers = {'Content-Disposition': "attachment; filename=\"%s\"; filename*=UTF-8''%s" % (safe, urllib.parse.quote(name))}
            return send_file(h, o['path'], 'application/octet-stream' if rest == 'download' else mime_for(o))
        return J(h, {'Items': [], 'TotalRecordCount': 0, 'StartIndex': 0})
    if p == '/playback/bitratetest':
        try:
            n = max(1, min(int(q.get('size') or 500000), 10_000_000))
        except ValueError:
            n = 500000
        return h.send(200, os.urandom(n), 'application/octet-stream', {})
    if p.startswith('/mediasegments/'):
        return J(h, {'Items': [], 'TotalRecordCount': 0, 'StartIndex': 0})

    # Streams
    m = re.fullmatch(r'/(videos|audio)/([0-9a-f-]{32,36})/(?:stream|universal|main|master)(?:\.[a-z0-9]+)?', p)
    if m:
        o = cat['items'].get(norm_id(m.group(2)))
        if not o or o.get('folder'):
            return J(h, {'error': 'NOT_FOUND'}, 404)
        if blocked(o):
            return J(h, {'error': 'UNSUPPORTED_4K_NAS'}, 403)
        if q.get('static', 'true').lower() == 'false' and o['kind'] == 'video':
            return remux_stream(h, o, q)
        return send_file(h, o['path'], mime_for(o))
    m = re.fullmatch(r'/videos/([0-9a-f-]{32,36})/(?:[0-9a-f-]{32,36}/)?subtitles/(\d+)(?:/(\d+))?/stream\.([a-z]+)', p)
    if m:
        o = cat['items'].get(norm_id(m.group(1)))
        if not o or o.get('folder') or o['kind'] != 'video':
            return J(h, {'error': 'NOT_FOUND'}, 404)
        return jf_subs.serve(h, o, int(m.group(2)), int(m.group(3) or 0), m.group(4))
    m = re.fullmatch(r'/videos/([0-9a-f-]{32,36})/.*', p)
    if m and '/images/' in p:
        return image(h, cat, cat['items'].get(norm_id(m.group(1))), p.split('/', 3)[3])

    # Wiedergabe-Meldungen
    if p in ('/sessions/playing', '/sessions/playing/progress', '/sessions/playing/stopped') and method == 'POST':
        return report(h, cat, user, p)
    if p in ('/sessions/playing/ping',):
        return none(h)
    if p.startswith('/sessions/capabilities'):
        body_json(h); return none(h)
    if p == '/sessions':
        return J(h, jf_sessions.sessions(catalog(), user, sid, q))
    if p == '/plugins':
        return J(h, plugins_list())
    if p.startswith('/plugins/'):
        if method != 'GET' and (not user or user[2] != 'admin'):
            return J(h, {'error': 'FORBIDDEN'}, 403)
        r = plugin_route(h, method, p)
        if r is not None:
            return r
    if p.startswith('/packages/') and method == 'GET':
        # Plugin-Details (sonst zeigt die Plugin-Seite „Fehler beim Abrufen aus dem Software-Depot“)
        name = urllib.parse.unquote(path.split('/', 2)[2] if path.count('/') >= 2 else '').split('?')[0]
        pl = next((x for x in plugins_list() if x['Name'] == name or norm_id(x['Id']) == norm_id(q.get('assemblyguid', ''))), None)
        if not pl:
            return J(h, {'error': 'NOT_FOUND'}, 404)
        return J(h, {'name': pl['Name'], 'description': pl['Description'], 'overview': pl['Description'], 'owner': 'Butchies',
                     'category': 'General', 'guid': pl['Id'], 'imageUrl': None,
                     'versions': [{'version': pl['Version'], 'VersionNumber': pl['Version'], 'changelog': '', 'targetAbi': '10.11.0.0',
                                   'sourceUrl': '', 'checksum': '', 'timestamp': '2026-11-18T00:00:00Z',
                                   'repositoryName': 'Butchies Media Center', 'repositoryUrl': ''}]})
    if p == '/web/configurationpages':
        return J(h, [{'Name': 'TMDb-Metadaten', 'EnableInMainMenu': False, 'PluginId': TMDB_PLUGIN_ID, 'DisplayName': 'TMDb-Metadaten'}] +
                 [{'Name': v[0], 'EnableInMainMenu': False, 'PluginId': i, 'DisplayName': v[0]} for i, v in switch_pages().items()])
    if p in ('/web/configurationpages', '/plugins', '/packages', '/repositories', '/scheduledtasks', '/notifications/types',
             '/livetv/channels', '/channels', '/playlists', '/collections', '/syncplay/list', '/devices'):
        if p == '/channels' or p == '/livetv/channels':
            return J(h, {'Items': [], 'TotalRecordCount': 0, 'StartIndex': 0})
        return J(h, [])
    if p == '/livetv/info':
        return J(h, {'Services': [], 'IsEnabled': False, 'EnabledUsers': []})
    if p == '/system/configuration':
        return J(h, {'EnableMetrics': False, 'IsStartupWizardCompleted': True, 'UICulture': 'de', 'ServerName': PRODUCT,
                     'EnableFolderView': False, 'EnableGroupingIntoCollections': False, 'DisplaySpecialsWithinSeasons': True,
                     'EnableExternalContentInSuggestions': False, 'QuickConnectAvailable': False, 'LibraryMonitorDelay': 60,
                     'ActivityLogRetentionDays': 30, 'CastReceiverApplications': []})
    if p == '/system/configuration/branding':
        return J(h, branding())
    if p.startswith('/system/configuration/'):
        return J(h, {})
    if p == '/library/virtualfolders' or p == '/library/mediafolders':
        lst = [{'Name': cat['items'][i]['name'], 'ItemId': i, 'Id': i, 'CollectionType': cat['items'][i]['collection'],
                'Locations': [], 'Type': 'CollectionFolder', 'LibraryOptions': {}} for i in cat['libs']]
        return J(h, lst if p.endswith('virtualfolders') else {'Items': lst, 'TotalRecordCount': len(lst)})
    if re.fullmatch(r'/users/[0-9a-f-]+/groupingoptions|/userviews/groupingoptions', p):
        return J(h, [{'Name': cat['items'][i]['name'], 'Id': i} for i in cat['libs']])
    if p == '/backup' and method == 'GET':
        return J(h, [])
    if p == '/library/refresh' and method == 'POST':
        if user[2] == 'admin' and S.scan_lock.acquire(blocking=False):
            threading.Thread(target=lambda: (S.run_scan('manual', lock_held=True), invalidate()), daemon=True).start()
        return none(h)
    if is_api(p):
        key = method + ' ' + p
        if key not in _unknown_logged and len(_unknown_logged) < 500:
            _unknown_logged.add(key)
            print('JF unbekannt:', key, flush=True)
        if method == 'GET':
            return J(h, {'Items': [], 'TotalRecordCount': 0, 'StartIndex': 0})
        return none(h)
    return False


API_ROOTS = ('system', 'branding', 'users', 'user', 'useritems', 'userviews', 'items', 'shows', 'movies', 'videos', 'audio', 'sessions',
             'displaypreferences', 'localization', 'quickconnect', 'genres', 'musicgenres', 'studios', 'persons', 'artists',
             'search', 'livetv', 'channels', 'playlists', 'collections', 'plugins', 'packages', 'scheduledtasks', 'library',
             'web', 'notifications', 'syncplay', 'devices', 'mediasegments', 'favoriteitems', 'userfavoriteitems', 'playeditems',
             'userplayeditems', 'repositories', 'playback', 'startup', 'trickplay', 'environment', 'auth', 'tmdb', 'lyrics', 'backup')


def is_api(p):
    return p.strip('/').split('/')[0] in API_ROOTS


# ---------------------------------------------------------------- Umpacken (MKV -> MP4) + Ton -> AAC
_ff_lock = threading.Lock()
_ff_running = []
MAX_FF = 2


def ffmpeg_bin():
    for c in (S.ROOT / 'bin' / 'ffmpeg', Path('/usr/bin/ffmpeg'), Path('/usr/local/bin/ffmpeg')):
        if c.is_file() and os.access(str(c), os.X_OK):
            return str(c)
    import shutil
    return shutil.which('ffmpeg')


MP4_NAMES = {'mp4', 'm4v', 'mov'}


def _codecs(profile_entry, key):
    return {c.strip().lower() for c in (profile_entry.get(key) or '').split(',') if c.strip()}


def _profile_ok(profile, container, vcodec, acodec):
    for d in profile.get('DirectPlayProfiles') or []:
        if (d.get('Type') or 'Video') != 'Video':
            continue
        conts = _codecs(d, 'Container')
        if conts and container not in conts and not (container in MP4_NAMES and conts & MP4_NAMES):
            continue
        vc, ac = _codecs(d, 'VideoCodec'), _codecs(d, 'AudioCodec')
        if vcodec and vc and vcodec not in vc:
            continue
        if acodec and ac and acodec not in ac:
            continue
        return True
    return False


def chosen_audio(o, aidx):
    streams = o.get('streams') or []
    aud = [(i, st) for i, st in enumerate(streams) if st['type'] == 'Audio']
    if aidx is not None:
        for i, st in aud:
            if i == aidx:
                return i, st
    return aud[0] if aud else (None, None)


def play_decision(o, profile, aidx=None):
    """'direct' | 'remux' (Video unverändert, MP4, Ton AAC) | 'none'"""
    if o['kind'] != 'video' or not profile:
        return 'direct'
    streams = o.get('streams') or []
    vcodec = next((st.get('codec') for st in streams if st['type'] == 'Video'), None)
    ai, ast = chosen_audio(o, aidx)
    acodec = ast.get('codec') if ast else None
    if not streams or not vcodec:
        return 'direct'  # unbekannt -> Browser probieren lassen
    container = 'mp4' if o['container'] in MP4_NAMES else ('mkv' if o['container'] in ('mkv', 'webm') else o['container'])
    first_audio = next((i for i, st in enumerate(streams) if st['type'] == 'Audio'), None)
    if (aidx is None or aidx == first_audio) and _profile_ok(profile, container, vcodec, acodec):
        return 'direct'
    if not ffmpeg_bin():
        return 'direct'
    if _profile_ok(profile, 'mp4', vcodec, 'aac'):
        return 'remux'
    # Der Browser meldet den Videocodec nicht (häufig bei x265/HEVC: viele Browser können es per Grafikkarte,
    # melden es aber nicht). Umrechnen schafft das NAS nicht – also umgepackt trotzdem versuchen.
    if vcodec in ('hevc', 'h264', 'av1', 'vp9'):
        return 'remux'
    return 'none'


def remux_stream(h, o, q):
    import subprocess
    ff = ffmpeg_bin()
    if not ff:
        return J(h, {'error': 'FFMPEG_MISSING'}, 500)
    try:
        start = max(0.0, int(q.get('starttimeticks') or 0) / TICKS)
    except ValueError:
        start = 0.0
    try:
        aidx = int(q['audiostreamindex']) if q.get('audiostreamindex') not in (None, '') else None
    except ValueError:
        aidx = None
    ai, ast = chosen_audio(o, aidx)
    streams = o.get('streams') or []
    vcodec = next((st.get('codec') for st in streams if st['type'] == 'Video'), '')
    cmd = [ff, '-hide_banner', '-loglevel', 'error', '-nostdin']
    if start > 0:
        cmd += ['-ss', '%.3f' % start]
    cmd += ['-i', o['path'], '-map', '0:v:0']
    if ai is not None:
        cmd += ['-map', '0:%d' % ai]
    cmd += ['-c:v', 'copy']
    if vcodec == 'hevc':
        cmd += ['-tag:v', 'hvc1']
    if ai is not None:
        if ast and ast.get('codec') == 'aac':
            cmd += ['-c:a', 'copy']
        else:
            cmd += ['-c:a', 'aac', '-ac', '2', '-b:a', '192k']
    cmd += ['-sn', '-dn', '-map_chapters', '-1', '-movflags', 'frag_keyframe+empty_moov+default_base_moof',
            '-frag_duration', '2000000', '-f', 'mp4', 'pipe:1']
    with _ff_lock:
        alive = [p for p in _ff_running if p.poll() is None]
        _ff_running[:] = alive
        if len(alive) >= MAX_FF:
            oldest = alive.pop(0)  # ältesten Vorgang beenden (meist der verlassene Stream nach dem Spulen)
            try:
                oldest.kill()
            except OSError:
                pass
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        alive.append(proc)
        _ff_running[:] = alive
    try:
        h.send_response(200)
        h.send_header('Content-Type', 'video/mp4')
        h.send_header('Cache-Control', 'no-store')
        h.send_header('Connection', 'close')
        h.send_header('X-Content-Type-Options', 'nosniff')
        h.end_headers()
        h.close_connection = True
        while True:
            buf = proc.stdout.read(65536)
            if not buf:
                break
            h.wfile.write(buf)
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass
    finally:
        try:
            proc.kill()
        except OSError:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
    return True


def mime_for(o):
    ext = '.' + (o.get('container') or '')
    return S.MIME.get(ext, mimetypes.guess_type('x' + ext)[0] or 'application/octet-stream')


def image(h, cat, o, rest):
    bits = rest.split('/') + ['', '', '']
    kind = bits[1].lower()
    idx = int(bits[2]) if bits[2].isdigit() else 0
    if o and o.get('type') == 'Person':
        src = jf_meta.person_image(o['tmdb'], o['profile']) if o.get('profile') and kind == 'primary' else None
    elif kind == 'logo':
        src = (o or {}).get('logo')
    elif kind == 'backdrop':
        bd = (o or {}).get('backdrops')
        if bd:
            src = bd[idx][0] if idx < len(bd) else None
        else:
            src = None if (o or {}).get('no_backdrop') else ((o or {}).get('backdrop') or (o or {}).get('cover'))
    elif kind in ('thumb', 'banner', 'art', 'disc'):
        ex = ((o or {}).get('extra_images') or {}).get(kind.capitalize())
        src = ex[0] if ex else None
    else:
        src = (o or {}).get('cover')
    if not o or not src:
        return h.send(404, b'', 'text/plain', {})
    cover = Path(src)
    try:
        if cover.is_symlink() or cover.stat().st_size > S.COVER_MAX_BYTES:
            return h.send(404, b'', 'text/plain', {})
    except OSError:
        return h.send(404, b'', 'text/plain', {})
    mime = {'.png': 'image/png', '.webp': 'image/webp'}.get(cover.suffix.lower(), 'image/jpeg')
    return send_file(h, cover, mime, 'public, max-age=604800')


def latest(h, cat, state, q, sid):
    pid = norm_id(q.get('parentid', ''))
    lib = cat['items'].get(pid, {}).get('lib') if pid else None
    try:
        limit = int(q.get('limit') or 16)
    except ValueError:
        limit = 16
    types = {t.lower() for t in csv(q.get('includeitemtypes'))}
    pool = []
    for o in cat['items'].values():
        if lib is not None and o['lib'] != lib:
            continue
        if o['type'] in ('Movie', 'Video', 'Series', 'MusicAlbum') and (not types or o['type'].lower() in types or
                                                                        ('episode' in types and o['type'] == 'Series')):
            pool.append(o)
    pool.sort(key=lambda o: -(o.get('date') or 0))
    return J(h, [dto(cat, o, state, sid) for o in pool[:limit]])


def report(h, cat, user, p):
    d = body_json(h)
    iid = norm_id(str(d.get('ItemId') or ''))
    o = cat['items'].get(iid)
    if not o or o.get('folder'):
        return none(h)
    pos = int((d.get('PositionTicks') or 0) / TICKS)
    now = int(time.time())
    with S.sqlite_session(S.DATA / 'library.sqlite') as c:
        r = c.execute('SELECT duration FROM playback_progress WHERE user_id=? AND media_id=?', (user[0], o['mid'])).fetchone()
        dur = int(r[0]) if r and r[0] else 0
        ticks = d.get('RunTimeTicks') or (d.get('NowPlayingItem') or {}).get('RunTimeTicks')
        if ticks:
            dur = int(ticks / TICKS)
        if o.get('duration'):
            dur = int(o['duration'])
        done = 1 if (dur and pos >= dur * 0.9) else 0
        if done:
            pos = 0  # fertig gesehen -> nächstes Mal von vorne
        c.execute('INSERT INTO playback_progress(user_id,media_id,position,duration,updated,completed) VALUES(?,?,?,?,?,?) '
                  'ON CONFLICT(user_id,media_id) DO UPDATE SET position=excluded.position,duration=CASE WHEN excluded.duration>0 THEN excluded.duration ELSE playback_progress.duration END,'
                  'updated=excluded.updated,completed=excluded.completed',
                  (user[0], o['mid'], pos, dur, now, done))
    jf_sessions.report(h, user, 'stopped' if p.endswith('/stopped') else 'progress' if p.endswith('/progress') else 'start', d, o)
    if p.endswith('/stopped'):
        notify_userdata(cat, user[0], [o['jid']])
    return none(h)


def meta_target(cat, o):
    """(art, schlüssel, objekt) für jf_meta – Serien brauchen ihren Ordner."""
    if o['type'] == 'Series':
        first = next((cat['items'][e] for z in o['children'] for e in cat['items'][z]['children']), None)
        return 'series', o['jid'], dict(o, _folder=str(jf_meta.series_folder(first['path'])) if first else '')
    return ('episode' if o['type'] == 'Episode' else 'movie'), o.get('mid') or o['jid'], o


EDIT_LIMITS = {'Name': 200, 'OriginalTitle': 200, 'Overview': 5000, 'OfficialRating': 20, 'ForcedSortName': 200}
# Jellyfin-Sperrfelder → eigene Felder
LOCK_MAP = {'Name': ('title',), 'OriginalTitle': ('original_title',), 'Overview': ('overview', 'tagline'),
            'Genres': ('genres',), 'OfficialRating': ('official_rating',), 'Cast': ('people',), 'Studios': ('studios',),
            'Tags': ('tags',), 'ProductionLocations': ('countries',), 'SortName': ('sort_name',)}


def _edit_values(d):
    """Werte aus dem Metadaten-Editor in eigene Felder übersetzen (nur geprüfte Werte)."""
    ch = {}
    def txt(k, lim):
        v = d.get(k)
        return str(v).strip()[:lim] if v is not None else None
    if txt('Name', 200):
        ch['title'] = txt('Name', 200)
    for src, dst in (('OriginalTitle', 'original_title'), ('Overview', 'overview'), ('OfficialRating', 'official_rating'),
                     ('ForcedSortName', 'sort_name')):
        v = txt(src, EDIT_LIMITS[src])
        if v is not None:
            ch[dst] = v
    if d.get('Status') in ('Continuing', 'Ended'):
        ch['status'] = d['Status']
    def lst(k, lim, n):
        return [str(x).strip()[:lim] for x in d[k] if str(x).strip()][:n] if isinstance(d.get(k), list) else None
    for src, dst, lim, n in (('Genres', 'genres', 60, 15), ('Tags', 'tags', 60, 30), ('ProductionLocations', 'countries', 60, 8)):
        v = lst(src, lim, n)
        if v is not None:
            ch[dst] = v
    if isinstance(d.get('Taglines'), list):
        ch['tagline'] = str(d['Taglines'][0]).strip()[:300] if d['Taglines'] else ''
    if isinstance(d.get('Studios'), list):
        ch['studios'] = [str(x.get('Name') if isinstance(x, dict) else x).strip()[:80] for x in d['Studios']
                         if str(x.get('Name') if isinstance(x, dict) else x).strip()][:8]
    if isinstance(d.get('People'), list):
        ch['people'] = [{'name': str(x.get('Name') or '').strip()[:120], 'role': str(x.get('Role') or '')[:120],
                         'type': str(x.get('Type') or 'Actor')[:20]} for x in d['People'] if isinstance(x, dict) and x.get('Name')][:40]
    try:
        y = int(d.get('ProductionYear')) if d.get('ProductionYear') not in (None, '') else None
        if y and 1880 <= y <= 2200:
            ch['year'] = y
    except (TypeError, ValueError):
        pass
    try:
        r = float(d.get('CommunityRating')) if d.get('CommunityRating') not in (None, '') else None
        if r is not None and 0 <= r <= 10:
            ch['rating'] = round(r, 1)
    except (TypeError, ValueError):
        pass
    pd = str(d.get('PremiereDate') or '')[:10]
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', pd):
        ch['premiere'] = pd
    return ch


def save_item_edit(h, cat, o, d):
    """„Metadaten bearbeiten“ – wird separat gespeichert, die Dateien des Nutzers bleiben unverändert.
    Gespeichert werden nur Felder, die wirklich geändert oder gesperrt wurden. Alles andere folgt weiter
    den Datei-Angaben bzw. TMDb. „Gesperrt“ hält den aktuellen Wert fest, auch wenn TMDb später etwas anderes liefert."""
    if o.get('type') in ('CollectionFolder', 'Person', 'MusicArtist', 'Playlist', 'BoxSet'):
        return J(h, {'error': 'NOT_SUPPORTED'}, 400)
    key = meta_target(cat, o)[1]
    cur = _edit_values(dto(cat, o, ({}, set()), '', full=True))   # so steht es gerade da
    new = _edit_values(d)
    old_ed = jf_meta.load_edits().get(key) or {}
    locked = [f for f in (d.get('LockedFields') or []) if f in LOCK_MAP] if isinstance(d.get('LockedFields'), list) else list(old_ed.get('locked') or [])
    lock_data = bool(d.get('LockData')) if 'LockData' in d else bool(old_ed.get('lock_data'))
    keep = {k for f in locked for k in LOCK_MAP[f]}
    ch = {}
    for k, v in new.items():
        if lock_data or k in keep or k in old_ed or cur.get(k) != v:
            ch[k] = v
    if o['type'] == 'Season' and 'title' in ch and ch['title'] == cur.get('title') and 'title' not in old_ed:
        ch.pop('title')
    ch['locked'] = locked
    ch['lock_data'] = lock_data
    pids = d.get('ProviderIds') or {}
    ids = {k.lower(): str(v).strip()[:40] for k, v in pids.items() if v and k.lower() in ('tmdb', 'imdb', 'tvdb')}
    if ids and ids != {k: v for k, v in (o.get('ids') or {}).items() if k in ('tmdb', 'imdb', 'tvdb')}:
        ch['ids'] = ids
    jf_meta.save_edit(key, ch)
    invalidate()
    return none(h)


def notify_userdata(cat, user_id, jids):
    """Live-Meldung an alle Geräte des Nutzers (gesehen/Fortschritt/Favorit)."""
    if not jf_ws.count():
        return
    try:
        st = user_state(user_id)
        lst = []
        for j in jids:
            o = cat['items'].get(j)
            if o:
                lst.append(user_data(cat, o, st))
                if o.get('parent') in cat['items'] and o['type'] in ('Episode', 'Audio'):
                    lst.append(user_data(cat, cat['items'][o['parent']], st))
        jf_ws.broadcast(user_id, {'MessageType': 'UserDataChanged', 'Data': {'UserId': uid_of(user_id), 'UserDataList': lst}})
    except Exception as e:
        print('JF Live-Meldung:', type(e).__name__, str(e)[:120], flush=True)


def display_prefs(h, method, user, pref_id, q):
    client = (q.get('client') or 'emby')[:40]
    if method == 'POST':
        d = body_json(h)
        with S.sqlite_session(S.DATA / 'library.sqlite') as c:
            c.execute('INSERT OR REPLACE INTO jf_displayprefs(user_id,pref_id,client,payload) VALUES(?,?,?,?)',
                      (user[0], pref_id[:80], client, json.dumps(d)[:50000]))
        return none(h)
    with S.sqlite_session(S.DATA / 'library.sqlite') as c:
        r = c.execute('SELECT payload FROM jf_displayprefs WHERE user_id=? AND pref_id=? AND client=?', (user[0], pref_id[:80], client)).fetchone()
    if r:
        try:
            d = json.loads(r[0])
            if pref_id == 'usersettings' and isinstance(d.get('CustomPrefs'), dict):
                d['CustomPrefs'].setdefault('skipForwardLength', '10000')  # wie Emby: 10 s vor (änderbar in den Einstellungen)
            return J(h, d)
        except ValueError:
            pass
    if pref_id == 'usersettings':
        return J(h, {'Id': pref_id, 'SortBy': 'SortName', 'RememberIndexing': False, 'CustomPrefs': {'skipForwardLength': '10000'},
                     'ScrollDirection': 'Horizontal', 'ShowBackdrop': True, 'RememberSorting': False, 'SortOrder': 'Ascending',
                     'ShowSidebar': False, 'Client': client})
    return J(h, {'Id': pref_id, 'SortBy': 'SortName', 'RememberIndexing': False, 'PrimaryImageHeight': 250, 'PrimaryImageWidth': 250,
                 'CustomPrefs': {}, 'ScrollDirection': 'Horizontal', 'ShowBackdrop': True, 'RememberSorting': False,
                 'SortOrder': 'Ascending', 'ShowSidebar': False, 'Client': client})


def localization(h, p):
    if p == '/localization/options':
        return J(h, [{'Name': 'Deutsch', 'Value': 'de'}, {'Name': 'English', 'Value': 'en-US'}])
    if p == '/localization/cultures':
        return J(h, [{'Name': 'German', 'DisplayName': 'Deutsch', 'TwoLetterISOLanguageName': 'de', 'ThreeLetterISOLanguageName': 'ger',
                      'ThreeLetterISOLanguageNames': ['ger', 'deu']},
                     {'Name': 'English', 'DisplayName': 'English', 'TwoLetterISOLanguageName': 'en', 'ThreeLetterISOLanguageName': 'eng',
                      'ThreeLetterISOLanguageNames': ['eng']}])
    if p == '/localization/countries':
        return J(h, [{'Name': 'DE', 'DisplayName': 'Deutschland', 'TwoLetterISORegionName': 'DE', 'ThreeLetterISORegionName': 'DEU'}])
    return J(h, [])


def login(h, sid):
    d = body_json(h)
    name = str(d.get('Username') or '')[:128]
    pw = str(d.get('Pw') or d.get('Password') or '')[:256]
    client = S.client_ip(h)
    now = time.time()
    with S.login_lock:
        hits = [t for t in S.login_attempts.get('jf:' + client, []) if now - t < 900]
        if len(hits) >= 5:
            return J(h, {'error': 'Zu viele Versuche. Bitte 15 Minuten warten.'}, 429)
        S.login_attempts['jf:' + client] = hits
    fields = auth_fields(h)
    device = (fields.get('Device') or 'Browser') + ' · ' + (fields.get('Client') or 'Jellyfin Web')
    token = S.accounts.login(name, pw, True, urllib.parse.unquote(device)[:80])
    if not token:
        with S.login_lock:
            S.login_attempts.setdefault('jf:' + client, []).append(now)
        return J(h, {'error': 'Benutzername oder Passwort falsch.'}, 401)
    with S.login_lock:
        S.login_attempts.pop('jf:' + client, None)
    user = S.accounts.user(token)
    ud = user_dto(user, sid)
    session = {'PlayState': {'CanSeek': False, 'IsPaused': False, 'IsMuted': False, 'RepeatMode': 'RepeatNone'},
               'AdditionalUsers': [], 'Capabilities': {'PlayableMediaTypes': [], 'SupportedCommands': []},
               'RemoteEndPoint': client, 'PlayableMediaTypes': [], 'Id': secrets.token_hex(16), 'UserId': ud['Id'],
               'UserName': user[1], 'Client': fields.get('Client', ''), 'LastActivityDate': iso(now),
               'DeviceName': fields.get('Device', ''), 'DeviceId': fields.get('DeviceId', ''),
               'ApplicationVersion': fields.get('Version', ''), 'IsActive': True, 'SupportsMediaControl': False,
               'SupportsRemoteControl': False, 'HasCustomDeviceName': False, 'ServerId': sid, 'SupportedCommands': []}
    return J(h, {'User': ud, 'SessionInfo': session, 'AccessToken': token, 'ServerId': sid})
