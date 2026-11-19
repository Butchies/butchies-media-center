"""Jellyfin-Verwaltungsbereich (Dashboard) für das Butchies Media Center: Benutzer, Bibliotheken,
Ordnerauswahl, Scan. Nutzt die vorhandene Bibliotheks- und Kontenlogik von server.py/auth.py."""
import json, os, re, time
from pathlib import Path
import jf_api as A

ROLE_ADMIN = 'admin'
CT_TO_CAT = {'movies': 'movies', 'tvshows': 'series', 'music': 'music'}
CAT_TO_CT = {'movies': 'movies', 'series': 'tvshows', 'music': 'music', 'mixed': 'mixed'}
ERR = {'INVALID_CREDENTIALS': 'Benutzername 3–32 Zeichen (Buchstaben, Ziffern, _ oder -), Passwort mindestens 6 Zeichen.',
       'USER_EXISTS': 'Diesen Benutzernamen gibt es schon.', 'USER_NOT_FOUND': 'Benutzer nicht gefunden.',
       'LAST_ADMIN': 'Der letzte Administrator kann nicht entfernt werden.', 'WRONG_PASSWORD': 'Aktuelles Passwort falsch.',
       'SELF_DELETE': 'Du kannst dich nicht selbst löschen.'}


def S():
    return A.S


def snd(h, *a):
    h.send(*a)
    return True


def err(h, code, status=400):
    msg = ERR.get(code) or (S().library_error(code)['message'] if hasattr(S(), 'library_error') else code)
    body = msg.encode()
    return snd(h, status, body, 'text/plain; charset=utf-8', {})


def user_from_jid(jid):
    jid = A.norm_id(jid)
    if not jid.startswith('b0'):
        return None
    try:
        uid = int(jid[2:], 16)
    except ValueError:
        return None
    for u in S().accounts.list_users():
        if u['id'] == uid:
            return (u['id'], u['name'], u['role'])
    return None


def abs_path(rel):
    return str(S().MEDIA / rel) if rel else str(S().MEDIA)


def rel_path(p):
    """Absoluter Pfad aus der Oberfläche → relativer Ordner im Medienordner (oder ValueError)."""
    root = S().MEDIA.resolve()
    p = (p or '').strip()
    if not p:
        raise ValueError('INVALID_FOLDER')
    cand = Path(p)
    if not cand.is_absolute():
        cand = S().MEDIA / p
    try:
        rel = cand.resolve().relative_to(root)
    except (ValueError, OSError):
        raise ValueError('INVALID_FOLDER')
    return S().normalize_library_folder('' if str(rel) == '.' else rel.as_posix())


# ---------------------------------------------------------------- Bibliotheken
def virtual_folders():
    with S().sqlite_session(S().DATA / 'library.sqlite') as c:
        rows = S().library_rows(c)
    out = []
    for r in rows:
        if not r['enabled']:
            continue
        locs = [abs_path(f) for f in r['folders']]
        out.append({'Name': r['name'], 'Locations': locs, 'CollectionType': CAT_TO_CT.get(r['category'], 'mixed'),
                    'ItemId': A.lib_of(r['id']), 'PrimaryImageItemId': A.lib_of(r['id']), 'RefreshStatus': 'Idle',
                    'LibraryOptions': lib_options(locs)})
    return out


def lib_options(locs):
    return {'Enabled': True, 'EnablePhotos': False, 'EnableRealtimeMonitor': False, 'EnableLUFSScan': False,
            'EnableChapterImageExtraction': False, 'ExtractChapterImagesDuringLibraryScan': False,
            'EnableTrickplayImageExtraction': False, 'ExtractTrickplayImagesDuringLibraryScan': False,
            'PathInfos': [{'Path': p} for p in locs], 'SaveLocalMetadata': False, 'EnableInternetProviders': False,
            'EnableAutomaticSeriesGrouping': False, 'EnableEmbeddedTitles': False, 'EnableEmbeddedExtrasTitles': False,
            'EnableEmbeddedEpisodeInfos': False, 'AutomaticRefreshIntervalDays': 0, 'PreferredMetadataLanguage': 'de',
            'MetadataCountryCode': 'DE', 'SeasonZeroDisplayName': 'Specials', 'MetadataSavers': [],
            'DisabledLocalMetadataReaders': [], 'LocalMetadataReaderOrder': [], 'DisabledSubtitleFetchers': [],
            'SubtitleFetcherOrder': [], 'DisabledMediaSegmentProviders': [], 'MediaSegmentProvideOrder': [],
            'SkipSubtitlesIfEmbeddedSubtitlesPresent': False, 'SkipSubtitlesIfAudioTrackMatches': False,
            'SubtitleDownloadLanguages': [], 'RequirePerfectSubtitleMatch': True, 'SaveSubtitlesWithMedia': True,
            'SaveLyricsWithMedia': False, 'SaveTrickplayWithMedia': False, 'DisabledLyricFetchers': [],
            'LyricFetcherOrder': [], 'PreferNonstandardArtistsTag': False, 'UseCustomTagDelimiters': False,
            'CustomTagDelimiters': [], 'DelimiterWhitelist': [], 'AutomaticallyAddToCollection': False,
            'AllowEmbeddedSubtitles': 'AllowAll', 'TypeOptions': []}


def find_lib(c, name):
    for r in S().library_rows(c):
        if r['name'].lower() == (name or '').strip().lower():
            return r
    return None


def save_lib(lib_id, name, category, folders):
    """Wie /api/libraries/save in server.py: prüft, speichert, räumt den Index auf, startet Scan."""
    srv = S()
    with srv.sqlite_session(srv.DATA / 'library.sqlite') as c:
        c.execute('BEGIN IMMEDIATE')
        name, category, folders, enabled = srv.validate_library(c, {'name': name, 'category': category, 'folders': folders, 'enabled': True}, lib_id)
        now = int(time.time())
        if lib_id is None:
            pos = c.execute('SELECT COALESCE(MAX(position),0)+1 FROM libraries').fetchone()[0]
            c.execute('INSERT INTO libraries(name,category,enabled,position,created,updated) VALUES(?,?,?,?,?,?)', (name, category, 1, pos, now, now))
            lib_id = c.execute('SELECT last_insert_rowid()').fetchone()[0]
        else:
            c.execute('UPDATE libraries SET name=?,category=?,enabled=1,updated=? WHERE id=?', (name, category, now, lib_id))
            c.execute('DELETE FROM library_folders WHERE library_id=?', (lib_id,))
        for f in folders:
            c.execute('INSERT INTO library_folders(library_id,path) VALUES(?,?)', (lib_id, f))
        srv.prune_library_index(c, lib_id, category, folders)
        c.execute('DELETE FROM media_stream_cache WHERE media_id NOT IN (SELECT id FROM media)')
    A.invalidate()
    srv.request_scan('library')
    return lib_id


def delete_lib(lib_id):
    srv = S()
    with srv.sqlite_session(srv.DATA / 'library.sqlite') as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute('DELETE FROM media WHERE library_id=?', (lib_id,))
        c.execute('DELETE FROM library_folders WHERE library_id=?', (lib_id,))
        c.execute('DELETE FROM libraries WHERE id=?', (lib_id,))
        c.execute('DELETE FROM media_stream_cache WHERE media_id NOT IN (SELECT id FROM media)')
    A.invalidate()


def scan_task():
    st = S().scan_status_snapshot(False)
    running = st.get('state') == 'running'
    last = None
    if st.get('finished'):
        last = {'StartTimeUtc': A.iso(st.get('started') or st['finished']), 'EndTimeUtc': A.iso(st['finished']),
                'Status': 'Completed' if not st.get('errors') else 'Failed', 'Name': 'Medienbibliothek scannen',
                'Key': 'RefreshLibrary', 'Id': 'b0' + '0' * 29 + '1'}
    return {'Name': 'Medienbibliothek scannen', 'State': 'Running' if running else 'Idle', 'Id': 'scan0000000000000000000000000001'[:32],
            'Category': 'Bibliothek', 'Description': 'Durchsucht die Medienordner nach neuen und geänderten Dateien.',
            'Key': 'RefreshLibrary', 'IsHidden': False, 'Triggers': [], 'LastExecutionResult': last,
            'CurrentProgressPercentage': 50.0 if running else None}


# ---------------------------------------------------------------- Weiche
def route(h, method, path, p, q, user, sid):
    """None = nicht zuständig."""
    lp = [x for x in p.strip('/').split('/')]
    admin = user[2] == ROLE_ADMIN
    acc = S().accounts

    # ---- eigenes Passwort / fremdes Passwort
    if method == 'POST' and (p == '/users/password' or (len(lp) == 3 and lp[0] == 'users' and lp[2] == 'password')):
        target_jid = q.get('userid') if p == '/users/password' else lp[1]
        target = user_from_jid(target_jid) if target_jid else user
        if not target:
            return err(h, 'USER_NOT_FOUND', 404)
        d = A.body_json(h)
        if target[0] != user[0] and not admin:
            return snd(h, 403, b'', 'text/plain', {})
        if d.get('ResetPassword'):
            return err(h, 'INVALID_CREDENTIALS')  # leeres Passwort gibt es hier nicht
        try:
            if target[0] == user[0] and not admin and not acc.login(user[1], str(d.get('CurrentPw') or d.get('CurrentPassword') or '')[:256]):
                raise ValueError('WRONG_PASSWORD')
            acc.set_password(target[0], str(d.get('NewPw') or '')[:256])
        except ValueError as e:
            return err(h, str(e))
        return A.none(h)
    if p == '/users/forgotpassword' or p == '/users/forgotpassword/pin':
        return A.J(h, {'Action': 'ContactAdmin', 'PinFile': '', 'PinExpirationDate': None})

    # ---- einzelner Benutzer (lesen/ändern/löschen)
    if len(lp) >= 2 and lp[0] == 'users' and A.norm_id(lp[1]) and lp[1] not in ('me',):
        target = user_from_jid(lp[1])
        if not target:
            return err(h, 'USER_NOT_FOUND', 404)
        if target[0] != user[0] and not admin:
            return snd(h, 403, b'', 'text/plain', {})
        if len(lp) == 2 and method == 'GET':
            return A.J(h, A.user_dto(target, sid))
        if len(lp) == 2 and method == 'DELETE':
            if not admin:
                return snd(h, 403, b'', 'text/plain', {})
            if target[0] == user[0]:
                return err(h, 'SELF_DELETE')
            try:
                acc.delete_user(target[0])
            except ValueError as e:
                return err(h, str(e))
            A.set_download(target[0], False)  # Nummer kann neu vergeben werden – Erlaubnis nicht vererben
            return A.none(h)
        if len(lp) == 2 and method == 'POST':  # Umbenennen
            d = A.body_json(h)
            new = str(d.get('Name') or '').strip()
            if new and new != target[1]:
                if not re.fullmatch(r'[a-zA-Z0-9_-]{3,32}', new):
                    return err(h, 'INVALID_CREDENTIALS')
                with S().sqlite_session(acc.db) as c:
                    if c.execute('SELECT 1 FROM users WHERE name=? AND id!=?', (new, target[0])).fetchone():
                        return err(h, 'USER_EXISTS')
                    c.execute('UPDATE users SET name=? WHERE id=?', (new, target[0]))
            return A.none(h)
        if len(lp) == 3 and lp[2] == 'policy' and method == 'POST':
            if not admin:
                return snd(h, 403, b'', 'text/plain', {})
            d = A.body_json(h)
            if 'EnableContentDownloading' in d:
                A.set_download(target[0], bool(d.get('EnableContentDownloading')))
            want = 'admin' if d.get('IsAdministrator') else 'user'
            if want != target[2]:
                with S().sqlite_session(acc.db) as c:
                    if want == 'user' and c.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0] <= 1:
                        return err(h, 'LAST_ADMIN')
                    c.execute('UPDATE users SET role=? WHERE id=?', (want, target[0]))
            return A.none(h)
        if len(lp) == 3 and lp[2] == 'configuration' and method == 'POST':
            cfg = A.body_json(h)
            with S().sqlite_session(S().DATA / 'library.sqlite') as c:
                c.execute('INSERT OR REPLACE INTO jf_userconfig(user_id,payload) VALUES(?,?)', (target[0], json.dumps(cfg)[:20000]))
            return A.none(h)
        if len(lp) == 3 and lp[2] == 'images':
            return snd(h, 404, b'', 'text/plain', {})
        return None

    if p == '/users/new' and method == 'POST':
        if not admin:
            return snd(h, 403, b'', 'text/plain', {})
        d = A.body_json(h)
        try:
            uid = acc.add_user(str(d.get('Name') or '').strip()[:64], str(d.get('Password') or '')[:256], 'user')
        except ValueError as e:
            return err(h, str(e))
        return A.J(h, A.user_dto((uid, str(d.get('Name')).strip(), 'user'), sid))

    # ---- Bibliotheken
    if p.startswith('/library/virtualfolders') or p.startswith('/environment/') or p == '/libraries/availableoptions':
        if not admin:
            return snd(h, 403, b'', 'text/plain', {})
    if p == '/library/virtualfolders' and method == 'GET':
        return A.J(h, virtual_folders())
    if p == '/library/virtualfolders' and method == 'POST':
        d = A.body_json(h)
        name = q.get('name') or ''
        cat = CT_TO_CAT.get((q.get('collectiontype') or '').lower(), 'mixed')
        paths = [x for x in (q.get('paths') or '').split(',') if x]
        paths += [pi.get('Path') for pi in ((d.get('LibraryOptions') or {}).get('PathInfos') or []) if pi.get('Path')]
        try:
            folders = sorted({rel_path(x) for x in paths})
            if not folders:
                raise ValueError('INVALID_FOLDERS')
            save_lib(None, name, cat, folders)
        except ValueError as e:
            return err(h, str(e))
        return A.none(h)
    if p == '/library/virtualfolders' and method == 'DELETE':
        with S().sqlite_session(S().DATA / 'library.sqlite') as c:
            r = find_lib(c, q.get('name'))
        if not r:
            return err(h, 'NOT_FOUND', 404)
        delete_lib(r['id'])
        return A.none(h)
    if p == '/library/virtualfolders/name' and method == 'POST':
        with S().sqlite_session(S().DATA / 'library.sqlite') as c:
            r = find_lib(c, q.get('name'))
        if not r:
            return err(h, 'NOT_FOUND', 404)
        try:
            save_lib(r['id'], q.get('newname') or '', r['category'], r['folders'])
        except ValueError as e:
            return err(h, str(e))
        return A.none(h)
    if p == '/library/virtualfolders/paths' and method in ('POST', 'DELETE'):
        d = A.body_json(h) if method == 'POST' else {}
        name = d.get('Name') or q.get('name')
        with S().sqlite_session(S().DATA / 'library.sqlite') as c:
            r = find_lib(c, name)
        if not r:
            return err(h, 'NOT_FOUND', 404)
        try:
            if method == 'POST':
                newp = d.get('Path') or (d.get('PathInfo') or {}).get('Path') or ''
                folders = sorted(set(r['folders']) | {rel_path(newp)})
            else:
                drop = rel_path(q.get('path') or '')
                folders = [f for f in r['folders'] if f != drop]
                if not folders:
                    return err(h, 'INVALID_FOLDERS')
            save_lib(r['id'], r['name'], r['category'], folders)
        except ValueError as e:
            return err(h, str(e))
        return A.none(h)
    if p in ('/library/virtualfolders/libraryoptions', '/library/virtualfolders/paths/update'):
        A.body_json(h)
        return A.none(h)
    if p == '/libraries/availableoptions':
        return A.J(h, {'MetadataSavers': [], 'MetadataReaders': [], 'SubtitleFetchers': [], 'LyricFetchers': [],
                       'MediaSegmentProviders': [], 'TypeOptions': []})

    # ---- Ordnerauswahl (nur innerhalb des Medienordners)
    root = S().MEDIA
    if p == '/environment/drives':
        return A.J(h, [{'Name': 'Medien (' + str(root) + ')', 'Path': str(root), 'Type': 'Directory'}])
    if p == '/environment/defaultdirectorybrowser':
        return A.J(h, {'Path': str(root)})
    if p == '/environment/networkshares':
        return A.J(h, [])
    if p == '/environment/parentpath':
        cur = Path(q.get('path') or str(root))
        par = cur.parent
        try:
            par.resolve().relative_to(root.resolve())
            return A.J(h, str(par))
        except ValueError:
            return A.J(h, str(root))
    if p == '/environment/directorycontents':
        try:
            rel = rel_path(q.get('path') or str(root))
        except ValueError:
            rel = ''
        base = root / rel if rel else root
        out = []
        try:
            for e in sorted(os.scandir(base), key=lambda e: e.name.lower()):
                if e.name.startswith('.') or e.is_symlink() or not e.is_dir(follow_symlinks=False):
                    continue
                out.append({'Name': e.name, 'Path': str(base / e.name), 'Type': 'Directory'})
                if len(out) >= 500:
                    break
        except OSError:
            pass
        return A.J(h, out)
    if p == '/environment/validatepath' and method == 'POST':
        d = A.body_json(h)
        try:
            rel_path(d.get('Path') or '')
            return A.none(h)
        except ValueError:
            return snd(h, 404, b'Ordner nicht gefunden oder ausserhalb des Medienordners.', 'text/plain; charset=utf-8', {})

    # ---- Scan / Aufgaben
    if p == '/library/refresh' and method == 'POST':
        if admin:
            S().request_scan('manual')
            A.invalidate()
        return A.none(h)
    if p == '/scheduledtasks':
        return A.J(h, [scan_task()] if admin else [])
    if lp[:2] == ['scheduledtasks', 'running'] and method == 'POST' and admin:
        S().request_scan('manual'); A.invalidate()
        return A.none(h)
    if lp[:2] == ['scheduledtasks', 'running'] and method == 'DELETE':
        return A.none(h)
    if len(lp) == 2 and lp[0] == 'scheduledtasks':
        return A.J(h, scan_task())

    # ---- System
    if p == '/system/activitylog/entries':
        return A.J(h, {'Items': [], 'TotalRecordCount': 0, 'StartIndex': 0})
    if p == '/system/info/storage':
        try:
            st = os.statvfs(str(root))
            total, free = st.f_blocks * st.f_frsize, st.f_bavail * st.f_frsize
        except OSError:
            total = free = 0
        folder = lambda n, pth: {'Path': pth, 'FreeSpace': free, 'UsedSpace': max(0, total - free), 'StorageType': 'ext4', 'DeviceId': n}
        return A.J(h, {'ProgramDataFolder': folder('data', str(S().DATA)), 'WebFolder': folder('web', str(S().ROOT / 'jfweb')),
                       'ImageCacheFolder': folder('img', str(S().DATA)), 'CacheFolder': folder('cache', str(S().DATA)),
                       'LogFolder': folder('log', str(S().DATA)), 'InternalMetadataFolder': folder('meta', str(S().DATA)),
                       'TranscodingTempFolder': folder('tmp', '/tmp'), 'Libraries': []})
    if p in ('/system/restart', '/system/shutdown') and method == 'POST':
        return snd(h, 400, 'Neustart/Herunterfahren bitte im WD-Dashboard unter Apps (App aus- und einschalten).'.encode(),
                      'text/plain; charset=utf-8', {})
    if p in ('/system/configuration/branding', '/branding/configuration') and method == 'POST':
        if not admin:
            return snd(h, 403, b'', 'text/plain', {})
        A.save_branding(A.body_json(h) or {})
        return A.none(h)
    if p == '/system/configuration' and method == 'POST':
        A.body_json(h)
        return A.none(h)
    if p == '/system/logs':
        return A.J(h, [])
    if p == '/devices':
        return A.J(h, {'Items': [], 'TotalRecordCount': 0, 'StartIndex': 0})
    if p == '/auth/providers':
        return A.J(h, [{'Name': 'Default', 'Id': 'Jellyfin.Server.Implementations.Users.DefaultAuthenticationProvider'}])
    if p == '/auth/passwordresetproviders':
        return A.J(h, [{'Name': 'Default', 'Id': 'Jellyfin.Server.Implementations.Users.DefaultPasswordResetProvider'}])
    if p == '/auth/keys':
        return A.J(h, {'Items': [], 'TotalRecordCount': 0, 'StartIndex': 0})
    return None
