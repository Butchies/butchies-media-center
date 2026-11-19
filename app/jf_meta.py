"""Metadaten für das Butchies Media Center: Plakate, Hintergründe, Logos, Beschreibung, Genres, Schauspieler.

Quellen (in dieser Reihenfolge, die eigene Datei gewinnt immer):
  1. lokale Dateien neben dem Film / im Serienordner: Film.nfo, movie.nfo, tvshow.nfo, Film-fanart.jpg, fanart.jpg …
  2. TMDB (themoviedb.org) – nur wenn im Dashboard → Plugins → „TMDb-Metadaten“ ein eigener API-Schlüssel eingetragen ist.
Heruntergeladene Bilder liegen in data/meta/ – die Mediendateien und Ordner des Nutzers werden nie verändert.
"""
import hashlib
import json
import os
import re
import ssl
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

S = None
A = None  # jf_api
_wake = threading.Event()
_state = {'running': False, 'done': 0, 'total': 0, 'last_error': '', 'last_run': 0}
TMDB_API = os.environ.get('BMC_TMDB_API', 'https://api.themoviedb.org/3')   # Umgebungsvariablen nur für Tests
TMDB_IMG = os.environ.get('BMC_TMDB_IMG', 'https://image.tmdb.org/t/p/')
IMG_EXT = ('.jpg', '.jpeg', '.png', '.webp')
MAX_IMG = 15 * 1024 * 1024
RETRY_NONE = 7 * 86400     # nichts gefunden -> nach 7 Tagen erneut versuchen
RETRY_ERR = 6 * 3600       # Netzfehler -> nach 6 Stunden


def setup(server_module, api_module):
    global S, A
    S, A = server_module, api_module
    with S.sqlite_session(S.DATA / 'library.sqlite') as c:
        c.execute('CREATE TABLE IF NOT EXISTS jf_meta (key TEXT PRIMARY KEY, sig TEXT NOT NULL, data TEXT NOT NULL, '
                  'tmdb_status TEXT, tmdb_at REAL)')
        # eigene Änderungen (Metadaten bearbeiten / Identifizieren) – haben Vorrang vor allem anderen
        c.execute('CREATE TABLE IF NOT EXISTS jf_edits (key TEXT PRIMARY KEY, data TEXT NOT NULL, updated REAL)')
    (S.DATA / 'meta' / 'img').mkdir(parents=True, exist_ok=True)
    (S.DATA / 'meta' / 'people').mkdir(parents=True, exist_ok=True)
    threading.Thread(target=_loop, name='jf-meta', daemon=True).start()


def wake():
    _wake.set()


def status():
    return dict(_state)


# ------------------------------------------------------------ Einstellungen
def settings():
    cfg = A.jf_settings().get('tmdb') or {}
    return {'ApiKey': cfg.get('ApiKey', ''), 'Language': cfg.get('Language') or 'de-DE',
            'Enabled': bool(cfg.get('Enabled', True)), 'Country': cfg.get('Country') or 'DE'}


def tmdb_on():
    s = settings()
    return bool(s['Enabled'] and s['ApiKey'].strip())


# ------------------------------------------------------------ lokale NFO-Dateien
def _txt(root, tag, limit=4000):
    e = root.find(tag)
    return (e.text or '').strip()[:limit] if e is not None and e.text else ''


def parse_nfo(path):
    try:
        p = Path(path)
        if p.is_symlink() or not p.is_file() or p.stat().st_size > 512 * 1024:
            return {}
        raw = p.read_bytes()
        # Kodi erlaubt eine Zeile mit Link nach dem XML – nur den XML-Teil lesen
        end = raw.rfind(b'>')
        root = ET.fromstring(raw[:end + 1]) if end > 0 else None
    except (OSError, ET.ParseError, ValueError):
        return {}
    if root is None or root.tag not in ('movie', 'episodedetails', 'tvshow', 'musicvideo'):
        return {}
    d = {}
    for k, tag in (('title', 'title'), ('original_title', 'originaltitle'), ('overview', 'plot'), ('tagline', 'tagline'),
                   ('official_rating', 'mpaa')):
        v = _txt(root, tag)
        if v:
            d[k] = v
    if not d.get('overview'):
        v = _txt(root, 'outline')
        if v:
            d['overview'] = v
    genres = [g.text.strip() for g in root.findall('genre') if g.text and g.text.strip()]
    if len(genres) == 1 and '/' in genres[0]:
        genres = [g.strip() for g in genres[0].split('/') if g.strip()]
    if genres:
        d['genres'] = genres[:12]
    studios = [g.text.strip() for g in root.findall('studio') if g.text and g.text.strip()]
    if studios:
        d['studios'] = studios[:6]
    for k, tag, n in (('tags', 'tag', 20), ('countries', 'country', 6)):
        vals = [g.text.strip()[:60] for g in root.findall(tag) if g.text and g.text.strip()]
        if vals:
            d[k] = vals[:n]
    v = _txt(root, 'sorttitle', 200)
    if v:
        d['sort_name'] = v
    v = _txt(root, 'status', 30)
    if v.lower() in ('continuing', 'ended'):
        d['status'] = v.capitalize()
    date = _txt(root, 'premiered', 32) or _txt(root, 'aired', 32) or _txt(root, 'releasedate', 32)
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})', date)
    if m:
        d['premiere'] = m.group(0)
    y = _txt(root, 'year', 4)
    if y.isdigit():
        d['year'] = int(y)
    elif m:
        d['year'] = int(m.group(1))
    r = _txt(root, 'rating', 8)
    if not r:
        e = root.find('ratings/rating/value')
        r = (e.text or '').strip() if e is not None else ''
    try:
        rv = float(r.replace(',', '.'))
        if 0 < rv <= 10:
            d['rating'] = round(rv, 1)
    except ValueError:
        pass
    people = []
    for a in root.findall('actor')[:25]:
        n = _txt(a, 'name', 120)
        if n:
            people.append({'name': n, 'role': _txt(a, 'role', 120), 'type': 'Actor'})
    for tag, typ in (('director', 'Director'), ('credits', 'Writer')):
        for e in root.findall(tag)[:4]:
            if e.text and e.text.strip():
                people.append({'name': e.text.strip()[:120], 'role': '', 'type': typ})
    if people:
        d['people'] = people
    ids = {}
    for u in root.findall('uniqueid'):
        t = (u.get('type') or '').lower()
        if u.text and t in ('tmdb', 'imdb', 'tvdb'):
            ids[t] = u.text.strip()
    for tag, t in (('tmdbid', 'tmdb'), ('imdbid', 'imdb'), ('tvdbid', 'tvdb')):
        v = _txt(root, tag, 40)
        if v:
            ids.setdefault(t, v)
    v = _txt(root, 'id', 40)
    if v.startswith('tt'):
        ids.setdefault('imdb', v)
    if ids:
        d['ids'] = ids
    return d


def _first(paths):
    root = S.MEDIA.resolve()
    for c in paths:
        try:
            if c.is_file() and not c.is_symlink() and root in c.resolve().parents and c.stat().st_size <= MAX_IMG:
                return c
        except OSError:
            pass
    return None


def _img_names(base, names):
    return [base / (n + e) for n in names for e in IMG_EXT]


def series_folder(ep_path):
    p = Path(ep_path).parent
    return p.parent if S.SEASON_FOLDER_RE.fullmatch(p.name) else p


def local_movie(o):
    src = Path(o['path'])
    nfo = parse_nfo(src.with_suffix('.nfo'))
    single = _single_video(src.parent)
    if not nfo and single:
        nfo = parse_nfo(src.parent / 'movie.nfo')
    names = [src.stem + '-fanart', src.stem + '-backdrop', src.stem + '.fanart']
    folder = ['fanart', 'backdrop', 'background'] if single else []
    bd = _first(_img_names(src.parent, names) + _img_names(src.parent, folder))
    if bd:
        nfo['backdrop'] = str(bd)
    return nfo


def local_episode(o):
    src = Path(o['path'])
    nfo = parse_nfo(src.with_suffix('.nfo'))
    th = _first(_img_names(src.parent, [src.stem + '-thumb', src.stem]))
    if th:
        nfo['thumb'] = str(th)
    return nfo


def local_series(folder):
    d = parse_nfo(folder / 'tvshow.nfo')
    for key, names in (('poster', ['poster', 'folder', 'cover']), ('backdrop', ['fanart', 'backdrop', 'background']),
                       ('logo', ['logo', 'clearlogo'])):
        f = _first(_img_names(folder, names))
        if f:
            d[key] = str(f)
    return d


def _single_video(folder):
    try:
        return sum(1 for e in os.scandir(folder) if e.is_file() and Path(e.name).suffix.lower() in S.VIDEO) <= 1
    except OSError:
        return False


def _sig(paths):
    out = []
    for p in paths:
        try:
            out.append('%x' % Path(p).stat().st_mtime_ns)
        except OSError:
            out.append('-')
    return ','.join(out)


def local_sig(o, kind):
    if kind == 'series':
        f = Path(o['_folder'])
        return _sig([f / 'tvshow.nfo', f]) + ('|t' if tmdb_on() else '')
    src = Path(o['path'])
    return _sig([src.with_suffix('.nfo'), src.parent / 'movie.nfo', src.parent]) + ('|t' if tmdb_on() else '')


# ------------------------------------------------------------ TMDB
_ctx = None


def _ssl():
    global _ctx
    if _ctx is None:
        ctx = ssl.create_default_context()
        if not ctx.get_ca_certs():
            for f in (os.environ.get('SSL_CERT_FILE') or '', '/etc/ssl/certs/ca-certificates.crt', '/etc/ssl/cert.pem',
                      '/etc/pki/tls/certs/ca-bundle.crt', '/opt/etc/ssl/certs/ca-certificates.crt',
                      '/usr/local/share/ca-certificates/ca-certificates.crt', '/usr/share/ca-certificates/ca-bundle.crt',
                      str(S.ROOT / 'cacert.pem')):
                if f and os.path.isfile(f):
                    try:
                        ctx.load_verify_locations(f)
                        break
                    except (OSError, ssl.SSLError):
                        pass
        _ctx = ctx
    return _ctx


class TmdbError(Exception):
    pass


def tmdb(path, **params):
    s = settings()
    key = s['ApiKey'].strip()
    headers = {'Accept': 'application/json', 'User-Agent': 'ButchiesMediaCenter/3'}
    if len(key) > 40:  # Lese-Token (v4)
        headers['Authorization'] = 'Bearer ' + key
    else:
        params['api_key'] = key
    url = TMDB_API + path + '?' + urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, '')})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20, context=_ssl()) as r:
                return json.loads(r.read(4_000_000).decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2 + attempt * 3); continue
            if e.code == 404:
                return None
            if e.code == 401:
                raise TmdbError('TMDB-Schlüssel ungültig (401)')
            raise TmdbError('TMDB-Fehler %d' % e.code)
        except (urllib.error.URLError, OSError, ValueError) as e:
            if attempt == 2:
                raise TmdbError('Keine Verbindung zu TMDB: %s' % (getattr(e, 'reason', None) or e))
            time.sleep(2)
    raise TmdbError('TMDB antwortet nicht')


def download(tmdb_path, size, target):
    if not tmdb_path:
        return None
    target = Path(target)
    if target.is_file() and target.stat().st_size > 0:
        return str(target)
    url = TMDB_IMG + size + tmdb_path
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'ButchiesMediaCenter/3'}),
                                    timeout=30, context=_ssl()) as r:
            data = r.read(MAX_IMG + 1)
        if len(data) > MAX_IMG or len(data) < 100:
            return None
        tmp = target.with_suffix(target.suffix + '.part')
        tmp.write_bytes(data); os.replace(str(tmp), str(target))
        return str(target)
    except (urllib.error.URLError, OSError):
        return None


def _imgfile(key, kind, tmdb_path):
    ext = Path(tmdb_path or '').suffix.lower() or '.jpg'
    return S.DATA / 'meta' / 'img' / ('%s-%s-%s%s' % (key, kind, hashlib.md5((tmdb_path or '').encode()).hexdigest()[:8], ext))


def _pick_logo(images, lang):
    logos = (images or {}).get('logos') or []
    for want in (lang[:2], 'en', None):
        for l in logos:
            if l.get('iso_639_1') == want and l.get('file_path', '').endswith('.png'):
                return l['file_path']
    return None


def _people(credits):
    out = []
    for c in ((credits or {}).get('cast') or [])[:20]:
        out.append({'name': c.get('name') or '', 'role': c.get('character') or '', 'type': 'Actor',
                    'tmdb': c.get('id'), 'profile': c.get('profile_path')})
    for c in ((credits or {}).get('crew') or []):
        if c.get('job') in ('Director', 'Screenplay', 'Writer') and len(out) < 30:
            out.append({'name': c.get('name') or '', 'role': '', 'type': 'Director' if c['job'] == 'Director' else 'Writer',
                        'tmdb': c.get('id'), 'profile': c.get('profile_path')})
    return [p for p in out if p['name']]


def fetch_movie(key, name, year, ids):
    s = settings(); lang = s['Language']
    tid = (ids or {}).get('tmdb')
    if not tid and (ids or {}).get('imdb'):
        r = tmdb('/find/' + ids['imdb'], external_source='imdb_id') or {}
        hit = (r.get('movie_results') or [None])[0]
        tid = hit and hit.get('id')
    if not tid:
        res = (tmdb('/search/movie', query=name, year=year or '', language=lang, include_adult='false') or {}).get('results') or []
        if not res and year:
            res = (tmdb('/search/movie', query=name, language=lang, include_adult='false') or {}).get('results') or []
        if not res:
            return None
        tid = res[0]['id']
    d = tmdb('/movie/%s' % tid, language=lang, append_to_response='credits,images,release_dates,keywords',
             include_image_language='%s,en,null' % lang[:2])
    if not d:
        return None
    out = {'title': d.get('title'), 'original_title': d.get('original_title'), 'overview': d.get('overview') or '',
           'tagline': d.get('tagline') or '', 'genres': [g['name'] for g in d.get('genres') or []],
           'studios': [c['name'] for c in (d.get('production_companies') or [])[:4]],
           'premiere': d.get('release_date') or '', 'rating': round(d['vote_average'], 1) if d.get('vote_average') else None,
           'people': _people(d.get('credits')), 'ids': {'tmdb': str(d['id'])},
           'tags': [k['name'] for k in ((d.get('keywords') or {}).get('keywords') or [])[:15] if k.get('name')],
           'countries': [c['name'] for c in (d.get('production_countries') or [])[:4] if c.get('name')]}
    if d.get('imdb_id'):
        out['ids']['imdb'] = d['imdb_id']
    if out['premiere'][:4].isdigit():
        out['year'] = int(out['premiere'][:4])
    if not out['overview'] and lang[:2] != 'en':
        en = tmdb('/movie/%s' % tid, language='en-US') or {}
        out['overview'] = en.get('overview') or ''
    for r in ((d.get('release_dates') or {}).get('results') or []):
        if r.get('iso_3166_1') == s['Country']:
            cert = next((x.get('certification') for x in r.get('release_dates') or [] if x.get('certification')), '')
            if cert:
                out['official_rating'] = ('FSK-' + cert) if s['Country'] == 'DE' and cert.isdigit() else cert
    out['poster'] = download(d.get('poster_path'), 'w780', _imgfile(key, 'poster', d.get('poster_path')))
    out['backdrop'] = download(d.get('backdrop_path'), 'w1280', _imgfile(key, 'backdrop', d.get('backdrop_path')))
    lp = _pick_logo(d.get('images'), lang)
    out['logo'] = download(lp, 'w500', _imgfile(key, 'logo', lp))
    return out


def fetch_series(key, name, year, ids):
    s = settings(); lang = s['Language']
    tid = (ids or {}).get('tmdb')
    if not tid and (ids or {}).get('tvdb'):
        r = tmdb('/find/' + ids['tvdb'], external_source='tvdb_id') or {}
        hit = (r.get('tv_results') or [None])[0]
        tid = hit and hit.get('id')
    if not tid:
        res = (tmdb('/search/tv', query=name, first_air_date_year=year or '', language=lang) or {}).get('results') or []
        if not res and year:
            res = (tmdb('/search/tv', query=name, language=lang) or {}).get('results') or []
        if not res:
            return None
        tid = res[0]['id']
    d = tmdb('/tv/%s' % tid, language=lang, append_to_response='credits,images,content_ratings,external_ids,keywords',
             include_image_language='%s,en,null' % lang[:2])
    if not d:
        return None
    out = {'title': d.get('name'), 'original_title': d.get('original_name'), 'overview': d.get('overview') or '',
           'tagline': d.get('tagline') or '', 'genres': [g['name'] for g in d.get('genres') or []],
           'studios': [c['name'] for c in (d.get('networks') or [])[:3]],
           'premiere': d.get('first_air_date') or '', 'rating': round(d['vote_average'], 1) if d.get('vote_average') else None,
           'people': _people(d.get('credits')), 'ids': {'tmdb': str(d['id'])},
           'status': 'Continuing' if d.get('in_production') else 'Ended',
           'tags': [k['name'] for k in ((d.get('keywords') or {}).get('results') or [])[:15] if k.get('name')],
           'countries': [c['name'] for c in (d.get('production_countries') or [])[:4] if c.get('name')]}

    ext = d.get('external_ids') or {}
    if ext.get('imdb_id'):
        out['ids']['imdb'] = ext['imdb_id']
    if ext.get('tvdb_id'):
        out['ids']['tvdb'] = str(ext['tvdb_id'])
    if out['premiere'][:4].isdigit():
        out['year'] = int(out['premiere'][:4])
    if not out['overview'] and lang[:2] != 'en':
        out['overview'] = (tmdb('/tv/%s' % tid, language='en-US') or {}).get('overview') or ''
    for r in ((d.get('content_ratings') or {}).get('results') or []):
        if r.get('iso_3166_1') == s['Country'] and r.get('rating'):
            out['official_rating'] = ('FSK-' + r['rating']) if s['Country'] == 'DE' and r['rating'].isdigit() else r['rating']
    out['poster'] = download(d.get('poster_path'), 'w780', _imgfile(key, 'poster', d.get('poster_path')))
    out['backdrop'] = download(d.get('backdrop_path'), 'w1280', _imgfile(key, 'backdrop', d.get('backdrop_path')))
    lp = _pick_logo(d.get('images'), lang)
    out['logo'] = download(lp, 'w500', _imgfile(key, 'logo', lp))
    out['seasons'] = {}
    return out


def fetch_season(series_key, tid, season):
    s = settings()
    d = tmdb('/tv/%s/season/%d' % (tid, season), language=s['Language'])
    if not d:
        return {}
    eps = {}
    for e in d.get('episodes') or []:
        n = e.get('episode_number')
        if n is None:
            continue
        eps[n] = {'title': e.get('name') or '', 'overview': e.get('overview') or '', 'premiere': e.get('air_date') or '',
                  'rating': round(e['vote_average'], 1) if e.get('vote_average') else None, 'still': e.get('still_path')}
    poster = download(d.get('poster_path'), 'w500', _imgfile(series_key, 's%d' % season, d.get('poster_path')))
    return {'episodes': eps, 'poster': poster, 'overview': d.get('overview') or ''}


def person_image(tmdb_id, profile):
    target = S.DATA / 'meta' / 'people' / ('%s%s' % (int(tmdb_id), Path(profile or '').suffix or '.jpg'))
    if target.is_file():
        return str(target)
    if not tmdb_on() or not profile:
        return None
    return download(profile, 'w185', target)


# ------------------------------------------------------------ Speicher
def load_all():
    out = {}
    try:
        with S.sqlite_session(S.DATA / 'library.sqlite') as c:
            for k, d in c.execute('SELECT key,data FROM jf_meta'):
                try:
                    out[k] = json.loads(d)
                except ValueError:
                    pass
    except Exception:
        pass
    return out


def load_edits():
    out = {}
    try:
        with S.sqlite_session(S.DATA / 'library.sqlite') as c:
            for k, d in c.execute('SELECT key,data FROM jf_edits'):
                try:
                    out[k] = json.loads(d)
                except ValueError:
                    pass
    except Exception:
        pass
    return out


def save_edit(key, changes):
    old = load_edits().get(key) or {}
    old.update(changes)
    with S.sqlite_session(S.DATA / 'library.sqlite') as c:
        c.execute('INSERT OR REPLACE INTO jf_edits(key,data,updated) VALUES(?,?,?)', (key, json.dumps(old, ensure_ascii=False), time.time()))


def drop_edit(key, fields):
    """Eigene Änderungen für bestimmte Felder verwerfen (z. B. „Alle Bilder ersetzen“)."""
    old = load_edits().get(key)
    if not old:
        return
    for f in fields:
        old.pop(f, None)
    with S.sqlite_session(S.DATA / 'library.sqlite') as c:
        if old:
            c.execute('INSERT OR REPLACE INTO jf_edits(key,data,updated) VALUES(?,?,?)', (key, json.dumps(old, ensure_ascii=False), time.time()))
        else:
            c.execute('DELETE FROM jf_edits WHERE key=?', (key,))


def search(kind, name, year, ids):
    """Treffer für „Identifizieren“ (Jellyfin RemoteSearchResult)."""
    s = settings(); lang = s['Language']
    res = []
    tid = (ids or {}).get('tmdb')
    if tid:
        d = tmdb('/%s/%s' % ('tv' if kind == 'series' else 'movie', tid), language=lang)
        res = [d] if d else []
    elif (ids or {}).get('imdb'):
        r = tmdb('/find/' + ids['imdb'], external_source='imdb_id') or {}
        res = r.get('tv_results' if kind == 'series' else 'movie_results') or []
    elif (ids or {}).get('tvdb'):
        r = tmdb('/find/' + ids['tvdb'], external_source='tvdb_id') or {}
        res = r.get('tv_results' if kind == 'series' else 'movie_results') or []
    elif name:
        if kind == 'series':
            res = (tmdb('/search/tv', query=name, first_air_date_year=year or '', language=lang) or {}).get('results') or []
        else:
            res = (tmdb('/search/movie', query=name, year=year or '', language=lang, include_adult='false') or {}).get('results') or []
    out = []
    for r in res[:20]:
        date = r.get('first_air_date' if kind == 'series' else 'release_date') or ''
        x = {'Name': r.get('name' if kind == 'series' else 'title') or '', 'ProviderIds': {'Tmdb': str(r['id'])},
             'SearchProviderName': 'TheMovieDb', 'Overview': r.get('overview') or '', 'AlbumArtist': None, 'Artists': []}
        if date[:4].isdigit():
            x['ProductionYear'] = int(date[:4]); x['PremiereDate'] = date + 'T00:00:00.0000000Z'
        if r.get('poster_path'):
            x['ImageUrl'] = TMDB_IMG + 'w185' + r['poster_path']
        out.append(x)
    return out


def identify(kind, key, o, tmdb_id):
    """Treffer fest zuordnen und sofort neu laden."""
    save_edit(key, {'ids': {'tmdb': str(tmdb_id)}})
    local = local_series(Path(o['_folder'])) if kind == 'series' else local_movie(o)
    local['ids'] = dict(local.get('ids') or {}, tmdb=str(tmdb_id))
    online = (fetch_series if kind == 'series' else fetch_movie)(key, local.get('title') or o['name'], None, local['ids'])
    data = merge(local, online)
    data['_online'] = online
    _save(key, local_sig(o, kind), data, 'ok' if online else 'none', time.time())
    if kind == 'series':  # Folgen mit der neuen Serie neu abgleichen
        cat = A.catalog()
        eps = [cat['items'][e]['mid'] for z in cat['items'][o['jid']]['children'] for e in cat['items'][z]['children']]
        seasons = list(cat['items'][o['jid']]['children'])
        with S.sqlite_session(S.DATA / 'library.sqlite') as c:
            for k in eps + seasons:
                c.execute('DELETE FROM jf_meta WHERE key=?', (k,))
    A.invalidate()
    wake()


def _save(key, sig, data, status_, at):
    with S.sqlite_session(S.DATA / 'library.sqlite') as c:
        c.execute('INSERT OR REPLACE INTO jf_meta(key,sig,data,tmdb_status,tmdb_at) VALUES(?,?,?,?,?)',
                  (key, sig, json.dumps(data, ensure_ascii=False), status_, at))


def forget(keys):
    with S.sqlite_session(S.DATA / 'library.sqlite') as c:
        for k in keys:
            c.execute('DELETE FROM jf_meta WHERE key=?', (k,))
    wake()


def merge(local, online):
    """Lokale Angaben gewinnen; Online-Daten füllen nur Lücken."""
    out = dict(online or {})
    for k, v in (local or {}).items():
        if v not in (None, '', [], {}):
            out[k] = v
    if online and local and online.get('ids'):
        out['ids'] = dict(online['ids'], **(local.get('ids') or {}))
    return out


# ------------------------------------------------------------ Hintergrund
def _work_list():
    cat = A.catalog()
    work = []
    for o in cat['items'].values():
        t = o.get('type')
        if t == 'Movie':
            work.append(('movie', o['mid'], o))
        elif t == 'Series':
            first = next((cat['items'][e] for z in o['children'] for e in cat['items'][z]['children']), None)
            if first:
                so = dict(o, _folder=str(series_folder(first['path'])))
                work.append(('series', o['jid'], so))
    for o in cat['items'].values():
        if o.get('type') == 'Episode':
            work.append(('episode', o['mid'], o))
    return work


def _loop():
    time.sleep(int(os.environ.get('BMC_META_DELAY', '30')))
    while True:
        try:
            changed = _run_once()
            if changed:
                A.invalidate()
        except Exception as e:  # nie abstürzen
            _state['last_error'] = '%s: %s' % (type(e).__name__, str(e)[:160])
            print('JF Metadaten:', _state['last_error'], flush=True)
        _state['running'] = False
        _wake.wait(600)
        _wake.clear()


def _run_once():
    work = _work_list()
    with S.sqlite_session(S.DATA / 'library.sqlite') as c:
        known = {k: (sig, st, at) for k, sig, st, at in c.execute('SELECT key,sig,tmdb_status,tmdb_at FROM jf_meta')}
    meta = load_all()
    edits = load_edits()
    _state.update(running=True, done=0, total=len(work), last_run=time.time())
    online = tmdb_on()
    changed = 0
    season_cache = {}
    now = time.time()
    for kind, key, o in work:
        _state['done'] += 1
        sig = local_sig(o, kind)
        old = known.get(key)
        if old and (edits.get(key) or {}).get('lock_data'):
            continue  # „Daten sperren“: nichts mehr automatisch ändern
        need_online = online and kind != 'episode' and (
            not old or old[1] in (None, 'off') or (old[1] == 'none' and now - (old[2] or 0) > RETRY_NONE) or
            (old[1] == 'error' and now - (old[2] or 0) > RETRY_ERR))
        if kind == 'episode':
            ser = meta.get(o['series_id']) or {}
            tid = (ser.get('ids') or {}).get('tmdb')
            ep_sig = sig + '|' + (tid or '')
            if old and old[0] == ep_sig:
                continue
            local = local_episode(o)
            online_ep = {}
            if online and tid and o.get('episode') is not None:
                sk = (tid, o['season'])
                if sk not in season_cache:
                    try:
                        season_cache[sk] = fetch_season(o['series_id'], tid, o['season'])
                    except TmdbError as e:
                        _state['last_error'] = str(e); season_cache[sk] = None
                    time.sleep(0.25)
                sea = season_cache[sk]
                if sea is None:
                    continue  # Netzfehler: später erneut
                ep = (sea.get('episodes') or {}).get(o['episode'])
                if ep:
                    online_ep = {k: v for k, v in ep.items() if k != 'still'}
                    if ep.get('still'):
                        online_ep['thumb'] = download(ep['still'], 'w300', _imgfile(key, 'still', ep['still']))
                if sea.get('poster'):
                    _season_poster(o['season_id'], sea['poster'])
            _save(key, ep_sig, merge(local, online_ep), 'local', now)
            changed += 1
            continue
        if old and old[0] == sig and not need_online:
            continue
        local = local_series(Path(o['_folder'])) if kind == 'series' else local_movie(o)
        forced = (edits.get(key) or {}).get('ids')
        if forced:
            local['ids'] = dict(local.get('ids') or {}, **forced)
        prev = meta.get(key) or {}
        online_data, st, at = (prev.get('_online') if old and old[0] == sig else None), (old[1] if old else 'off'), (old[2] if old else 0)
        if online and (need_online or not online_data):
            name = local.get('title') or o['name']
            year = local.get('year') or o.get('year')
            try:
                online_data = (fetch_series if kind == 'series' else fetch_movie)(key, name, year, local.get('ids'))
                st, at = ('ok' if online_data else 'none'), now
            except TmdbError as e:
                _state['last_error'] = str(e); st, at = 'error', now
                if 'ungültig' in str(e):
                    online = False
            time.sleep(0.3)
        elif not online:
            online_data, st = None, 'off'
        data = merge(local, online_data)
        data['_online'] = online_data
        _save(key, sig, data, st, at)
        meta[key] = data
        changed += 1
        if changed % 20 == 0:
            A.invalidate()
    return changed


def _season_poster(season_jid, path):
    with S.sqlite_session(S.DATA / 'library.sqlite') as c:
        row = c.execute('SELECT data FROM jf_meta WHERE key=?', (season_jid,)).fetchone()
        if row and json.loads(row[0]).get('poster') == path:
            return
        c.execute('INSERT OR REPLACE INTO jf_meta(key,sig,data,tmdb_status,tmdb_at) VALUES(?,?,?,?,?)',
                  (season_jid, 'season', json.dumps({'poster': path}), 'ok', time.time()))


# ------------------------------------------------------------ in den Katalog einbauen
def _tag(path):
    try:
        return '%x' % (Path(path).stat().st_mtime_ns // 1000000) + hashlib.md5(str(path).encode()).hexdigest()[:4]
    except OSError:
        return None


def person_id(name):
    return '90' + hashlib.md5(('person\x1f' + name.lower()).encode()).hexdigest()[:30]


EDIT_TEXT = ('overview', 'tagline', 'official_rating', 'premiere', 'status', 'original_title', 'sort_name')
EDIT_LIST = ('genres', 'studios', 'tags', 'countries')
NOT_FIELDS = ('ids', 'images', 'locked', 'lock_data')


def apply(items):
    """Metadaten in die Katalog-Objekte übernehmen. Gibt die Personen-Liste zurück.
    Reihenfolge: Datei-Angaben (NFO/Bilder) > TMDb, eigene Änderungen (jf_edits) gewinnen immer."""
    import jf_images
    meta = load_all()
    edits = load_edits()
    for k, e in edits.items():
        if k not in meta:
            meta[k] = {}
    people = {}
    for o in items.values():
        t = o.get('type')
        key = o['mid'] if t in ('Movie', 'Video', 'Episode') else o['jid'] if t in ('Series', 'Season', 'MusicAlbum') else None
        m = meta.get(key) if key else None
        if m is None:
            continue
        ed = edits.get(key) or {}
        edited = any(x not in NOT_FIELDS for x in ed)
        m = dict(m, **{x: v for x, v in ed.items() if x not in NOT_FIELDS})
        custom = o.get('custom') and 'title' not in ed
        for k in ('overview', 'genres', 'rating', 'year'):
            if k in ed:
                o[k] = ed[k]
        if ed.get('locked') or ed.get('lock_data'):
            o['locked'] = list(ed.get('locked') or []); o['lock_data'] = bool(ed.get('lock_data'))
        if edited:
            o['edited'] = True
        if m.get('title') and not custom and t in ('Movie', 'Video', 'Series', 'Episode', 'Season', 'MusicAlbum'):
            if t not in ('Season', 'MusicAlbum') or 'title' in ed:
                o['name'] = m['title']
        if m.get('original_title') and m.get('original_title') != o.get('name'):
            o['original_title'] = m['original_title']
        for k in EDIT_TEXT:
            if k == 'original_title':
                continue
            if m.get(k) and not (k == 'overview' and o.get('overview') and 'overview' not in ed):
                o[k] = m[k]
        for k in ('tags', 'countries'):
            if m.get(k):
                o[k] = m[k]
        if m.get('genres') and (not o.get('genres') or set(o['genres']) <= set(m['genres'])):
            o['genres'] = m['genres']
        if m.get('year') and not o.get('year'):
            o['year'] = m['year']
        if m.get('rating') and not o.get('rating'):
            o['rating'] = m['rating']
        if m.get('studios'):
            o['studios'] = m['studios']
        if m.get('ids'):
            o['ids'] = m['ids']
        poster = m.get('thumb') if t == 'Episode' else m.get('poster')
        own = bool(o.get('cover')) and (t == 'Movie' or (t == 'Episode' and Path(o['cover']).stem.lower().startswith(Path(o['path']).stem.lower())))
        if poster and not own:
            tg = _tag(poster)
            if tg:
                o['cover'], o['cover_tag'] = poster, tg
        if m.get('backdrop'):
            tg = _tag(m['backdrop'])
            if tg:
                o['backdrop'], o['backdrop_tag'] = m['backdrop'], tg
        if m.get('logo') and not o.get('logo'):
            tg = _tag(m['logo'])
            if tg:
                o['logo'], o['logo_tag'] = m['logo'], tg
        if m.get('people'):
            lst = []
            for p in m['people']:
                pid = person_id(p['name'])
                lst.append({'Name': p['name'], 'Id': pid, 'Role': p.get('role') or '', 'Type': p.get('type') or 'Actor'})
                pe = people.setdefault(pid, {'jid': pid, 'type': 'Person', 'name': p['name'], 'folder': True, 'lib': None,
                                             'parent': None, 'items': set(), 'date': 0})
                pe['items'].add(o['jid'])
                if p.get('tmdb') and p.get('profile') and not pe.get('profile'):
                    pe['tmdb'], pe['profile'] = p['tmdb'], p['profile']
                    pe['cover_tag'] = hashlib.md5(p['profile'].encode()).hexdigest()[:12]
            o['people'] = lst
        if isinstance(ed.get('images'), dict):
            jf_images.apply_edit(o, ed['images'])
    return people
