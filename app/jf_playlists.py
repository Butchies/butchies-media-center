"""Wiedergabelisten (Playlists) wie bei Jellyfin – pro Benutzer, gespeichert in library.sqlite."""
import hashlib
import json
import re
import secrets
import time

S = None
A = None
VIEW_ID = 'c1' + '0' * 30          # Bereich „Wiedergabelisten“ in der Seitenleiste
BOX_VIEW_ID = 'c2' + '0' * 30      # Bereich „Sammlungen“ (für alle Benutzer)


def setup(server_module, api_module):
    global S, A
    S, A = server_module, api_module
    with S.sqlite_session(S.DATA / 'library.sqlite') as c:
        c.execute('CREATE TABLE IF NOT EXISTS jf_playlists (id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, name TEXT NOT NULL, '
                  'media_type TEXT, created REAL NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS jf_playlist_items (playlist_id TEXT NOT NULL, entry_id TEXT NOT NULL, item_id TEXT NOT NULL, '
                  'pos INTEGER NOT NULL, PRIMARY KEY(playlist_id, entry_id))')
        if 'kind' not in {r[1] for r in c.execute('PRAGMA table_info(jf_playlists)')}:
            c.execute("ALTER TABLE jf_playlists ADD COLUMN kind TEXT NOT NULL DEFAULT 'playlist'")


def _new_id():
    return '92' + secrets.token_hex(15)


def with_playlists(cat, user):
    """Katalog-Sicht inkl. Wiedergabelisten dieses Benutzers und der gemeinsamen Sammlungen."""
    if not user:
        return cat
    with S.sqlite_session(S.DATA / 'library.sqlite') as c:
        pls = c.execute("SELECT id,name,media_type,created,kind FROM jf_playlists WHERE (kind='playlist' AND user_id=?) OR kind='boxset' "
                        'ORDER BY name COLLATE NOCASE', (user[0],)).fetchall()
        rows = c.execute("SELECT i.playlist_id,i.entry_id,i.item_id FROM jf_playlist_items i JOIN jf_playlists p ON p.id=i.playlist_id "
                         "WHERE (p.kind='playlist' AND p.user_id=?) OR p.kind='boxset' ORDER BY i.playlist_id,i.pos", (user[0],)).fetchall()
    if not pls:
        return cat
    items = dict(cat['items'])
    entries = {}
    for pid, eid, iid in rows:
        if iid in items:
            entries.setdefault(pid, []).append((eid, iid))
    views = {'playlist': {'jid': VIEW_ID, 'type': 'CollectionFolder', 'folder': True, 'lib': None, 'parent': None, 'name': 'Wiedergabelisten',
                          'collection': 'playlists', 'date': 0, 'cover': None, 'cover_tag': None, 'children': []},
             'boxset': {'jid': BOX_VIEW_ID, 'type': 'CollectionFolder', 'folder': True, 'lib': None, 'parent': None, 'name': 'Sammlungen',
                        'collection': 'boxsets', 'date': 0, 'cover': None, 'cover_tag': None, 'children': []}}
    for pid, name, mt, created, kind in pls:
        ent = entries.get(pid, [])
        view = views['boxset' if kind == 'boxset' else 'playlist']
        o = {'jid': pid, 'type': 'BoxSet' if kind == 'boxset' else 'Playlist', 'folder': True, 'lib': None, 'parent': view['jid'],
             'name': name, 'date': created, 'children': [i for _, i in ent], 'entries': ent, 'media_type': mt or 'Video',
             'cover': None, 'cover_tag': None, 'kind': kind}
        for _, i in ent:
            x = items[i]
            src = x if x.get('cover') else items.get(x.get('album_id') or x.get('series_id') or '', {})
            if src.get('cover'):
                o['cover'], o['cover_tag'] = src['cover'], src['cover_tag']
                break
        items[pid] = o
        view['children'].append(pid)
    libs = list(cat['libs'])
    for v in views.values():
        if v['children']:
            first = items[v['children'][0]]
            v['cover'], v['cover_tag'] = first.get('cover'), first.get('cover_tag')
            items[v['jid']] = v
            libs.append(v['jid'])
    return dict(cat, items=items, libs=libs)


def _owned(user, pid, write=False):
    with S.sqlite_session(S.DATA / 'library.sqlite') as c:
        r = c.execute('SELECT user_id,kind FROM jf_playlists WHERE id=?', (pid,)).fetchone()
    if not r:
        return False
    if r[1] == 'boxset':
        return not write or user[2] == 'admin'
    return r[0] == user[0]


def _add(pid, ids):
    with S.sqlite_session(S.DATA / 'library.sqlite') as c:
        pos = c.execute('SELECT COALESCE(MAX(pos),-1)+1 FROM jf_playlist_items WHERE playlist_id=?', (pid,)).fetchone()[0]
        for i in ids:
            c.execute('INSERT INTO jf_playlist_items(playlist_id,entry_id,item_id,pos) VALUES(?,?,?,?)', (pid, secrets.token_hex(16), i, pos))
            pos += 1


def _expand(cat, ids):
    """Ordner (Album, Serie, Staffel) in ihre Titel/Folgen auflösen."""
    out = []
    for i in ids:
        o = cat['items'].get(i)
        if not o:
            continue
        out += A.leaf_ids(cat, o) if o.get('folder') else [i]
    return out[:5000]


def route(h, method, p, q, user, cat, state, sid):
    """None = nicht zuständig. /Playlists (pro Benutzer) und /Collections (für alle, ändern nur Admin)."""
    if p == '/collections' and method == 'POST':
        if user[2] != 'admin':
            return A.J(h, {'error': 'FORBIDDEN'}, 403)
        d = A.body_json(h) or {}
        name = str(q.get('name') or d.get('Name') or 'Neue Sammlung').strip()[:120] or 'Sammlung'
        pid = _new_id()
        with S.sqlite_session(S.DATA / 'library.sqlite') as c:
            c.execute("INSERT INTO jf_playlists(id,user_id,name,media_type,created,kind) VALUES(?,?,?,?,?,'boxset')", (pid, 0, name, None, time.time()))
        ids = [A.norm_id(x) for x in A.csv(q.get('ids'))]
        _add(pid, [i for i in ids if i in cat['items']])
        return A.J(h, {'Id': pid})
    m = re.fullmatch(r'/collections/([0-9a-f-]{32,36})/items', p)
    if m:
        pid = A.norm_id(m.group(1))
        if not _owned(user, pid, write=True):
            return A.J(h, {'error': 'FORBIDDEN'}, 403)
        ids = [A.norm_id(x) for x in A.csv(q.get('ids'))]
        if method == 'POST':
            _add(pid, [i for i in ids if i in cat['items'] and i not in cat['items'].get(pid, {}).get('children', [])])
        elif method == 'DELETE':
            with S.sqlite_session(S.DATA / 'library.sqlite') as c:
                for i in ids:
                    c.execute('DELETE FROM jf_playlist_items WHERE playlist_id=? AND item_id=?', (pid, i))
        return A.none(h)
    if p == '/playlists' and method == 'POST':
        d = A.body_json(h) or {}
        name = str(d.get('Name') or q.get('name') or 'Neue Wiedergabeliste').strip()[:120] or 'Wiedergabeliste'
        ids = [A.norm_id(x) for x in (d.get('Ids') or A.csv(q.get('ids')))]
        pid = _new_id()
        with S.sqlite_session(S.DATA / 'library.sqlite') as c:
            c.execute("INSERT INTO jf_playlists(id,user_id,name,media_type,created,kind) VALUES(?,?,?,?,?,'playlist')",
                      (pid, user[0], name, str(d.get('MediaType') or q.get('mediatype') or '')[:10] or None, time.time()))
        _add(pid, _expand(cat, [i for i in ids if i]))
        return A.J(h, {'Id': pid})
    m = re.fullmatch(r'/playlists/([0-9a-f-]{32,36})(/items(?:/([0-9a-f]+)/move/(\d+))?|/users(?:/[0-9a-f-]+)?)?', p)
    if not m:
        return None
    pid = A.norm_id(m.group(1))
    if not _owned(user, pid, write=method != 'GET'):
        return A.J(h, {'error': 'NOT_FOUND'}, 404)
    sub = m.group(2) or ''
    if sub == '':
        if method == 'GET':
            o = cat['items'].get(pid, {})
            return A.J(h, {'OpenAccess': False, 'Shares': [], 'ItemIds': o.get('children', [])})
        if method == 'POST':  # umbenennen
            d = A.body_json(h) or {}
            if d.get('Name'):
                with S.sqlite_session(S.DATA / 'library.sqlite') as c:
                    c.execute('UPDATE jf_playlists SET name=? WHERE id=?', (str(d['Name']).strip()[:120], pid))
            return A.none(h)
    if sub.startswith('/users'):
        if method != 'GET':
            return A.none(h)
        if sub.count('/') >= 2:
            return A.J(h, {'UserId': A.uid_of(user[0]), 'CanEdit': True})
        return A.J(h, [])
    if m.group(3):  # verschieben
        eid, new = m.group(3), int(m.group(4))
        with S.sqlite_session(S.DATA / 'library.sqlite') as c:
            order = [r[0] for r in c.execute('SELECT entry_id FROM jf_playlist_items WHERE playlist_id=? ORDER BY pos', (pid,))]
            if eid in order:
                order.remove(eid); order.insert(max(0, min(new, len(order))), eid)
                for n, e in enumerate(order):
                    c.execute('UPDATE jf_playlist_items SET pos=? WHERE playlist_id=? AND entry_id=?', (n, pid, e))
        return A.none(h)
    if method == 'POST':
        ids = [A.norm_id(x) for x in A.csv(q.get('ids'))]
        if not ids:
            d = A.body_json(h) or {}
            ids = [A.norm_id(x) for x in d.get('Ids') or []]
        _add(pid, _expand(cat, [i for i in ids if i]))
        return A.none(h)
    if method == 'DELETE':
        eids = A.csv(q.get('entryids'))
        with S.sqlite_session(S.DATA / 'library.sqlite') as c:
            for e in eids:
                c.execute('DELETE FROM jf_playlist_items WHERE playlist_id=? AND entry_id=?', (pid, e))
        return A.none(h)
    # GET Einträge
    o = cat['items'].get(pid, {})
    out = []
    for eid, iid in o.get('entries', []):
        d = A.dto(cat, cat['items'][iid], state, sid)
        d['PlaylistItemId'] = eid
        out.append(d)
    start = int(q.get('startindex') or 0); lim = int(q.get('limit') or 0) or len(out)
    return A.J(h, {'Items': out[start:start + lim], 'TotalRecordCount': len(out), 'StartIndex': start})


def delete(user, pid):
    if not _owned(user, pid, write=True):
        return False
    with S.sqlite_session(S.DATA / 'library.sqlite') as c:
        c.execute('DELETE FROM jf_playlist_items WHERE playlist_id=?', (pid,))
        c.execute('DELETE FROM jf_playlists WHERE id=?', (pid,))
    return True
