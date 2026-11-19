"""Wiedergabe-Sitzungen und Geräte.

- Welche Geräte gerade verbunden sind und was sie abspielen (Dashboard → „Aktive Geräte“, GET /Sessions)
- Geräteübersicht (Dashboard → Geräte, GET/DELETE /Devices)
- Verlauf jeder Wiedergabe in der Tabelle playback_sessions (Start, letzte Position, Pause, Ende)
- Warteschlange des Players (NowPlayingQueue), damit der Player-Reiter „Warteschlange“ sie anzeigen kann
Alles bleibt auf dem NAS, nichts geht ins Internet.
"""
import re
import secrets
import threading
import time

S = None
A = None
ACTIVE = 600          # Gerät gilt 10 Minuten nach der letzten Anfrage als aktiv
_lock = threading.Lock()
_live = {}            # device_id -> dict
_saved = {}           # device_id -> Zeitpunkt der letzten Speicherung


def setup(server_module, api_module):
    global S, A
    S, A = server_module, api_module
    with S.sqlite_session(S.DATA / 'library.sqlite') as c:
        c.execute('CREATE TABLE IF NOT EXISTS jf_devices (device_id TEXT PRIMARY KEY, user_id INTEGER, user_name TEXT, client TEXT, '
                  'device TEXT, version TEXT, last_seen INTEGER NOT NULL, custom_name TEXT)')
        c.execute('CREATE TABLE IF NOT EXISTS playback_sessions (id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, media_id TEXT NOT NULL, '
                  'device_id TEXT, started INTEGER NOT NULL, last_progress INTEGER, position INTEGER NOT NULL DEFAULT 0, '
                  'paused INTEGER NOT NULL DEFAULT 0, method TEXT, stopped INTEGER)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_playback_user ON playback_sessions(user_id,stopped)')
        # Verlauf nicht endlos wachsen lassen (älter als 1 Jahr)
        c.execute('DELETE FROM playback_sessions WHERE started<?', (int(time.time()) - 365 * 86400,))


def _clean(v, n=80):
    return re.sub(r'[\x00-\x1f]', '', str(v or ''))[:n]


def client_info(h):
    f = A.auth_fields(h)
    did = _clean(f.get('DeviceId') or h.headers.get('X-Emby-Device-Id') or '', 120)
    return {'device_id': did, 'client': _clean(f.get('Client') or h.headers.get('X-Emby-Client') or 'Browser'),
            'device': _clean(f.get('Device') or h.headers.get('X-Emby-Device-Name') or 'Gerät'),
            'version': _clean(f.get('Version') or '', 30)}


def touch(h, user):
    """Bei jeder angemeldeten Anfrage: Gerät als aktiv merken (schnell, nur im Speicher; DB höchstens 1× pro Minute)."""
    if not user or not user[0]:
        return
    ci = client_info(h)
    if not ci['device_id']:
        return
    now = int(time.time())
    try:
        ip = A.S.client_ip(h) if hasattr(A.S, 'client_ip') else h.client_address[0]
    except Exception:
        ip = ''
    with _lock:
        s = _live.get(ci['device_id'])
        if not s or s['user_id'] != user[0]:
            s = {'id': secrets.token_hex(16), 'user_id': user[0], 'user_name': user[1], 'play': None, 'queue': []}
            _live[ci['device_id']] = s
        s.update(ci, last=now, ip=str(ip)[:60])
        due = now - _saved.get(ci['device_id'], 0) > 60
        if due:
            _saved[ci['device_id']] = now
        if len(_live) > 300:  # alte Einträge wegräumen
            for k in sorted(_live, key=lambda k: _live[k]['last'])[:100]:
                _live.pop(k, None)
    if due:
        try:
            with S.sqlite_session(S.DATA / 'library.sqlite') as c:
                c.execute('INSERT INTO jf_devices(device_id,user_id,user_name,client,device,version,last_seen) VALUES(?,?,?,?,?,?,?) '
                          'ON CONFLICT(device_id) DO UPDATE SET user_id=excluded.user_id,user_name=excluded.user_name,client=excluded.client,'
                          'device=excluded.device,version=excluded.version,last_seen=excluded.last_seen',
                          (ci['device_id'], user[0], user[1], ci['client'], ci['device'], ci['version'], now))
        except Exception as e:
            print('JF Geräte:', type(e).__name__, str(e)[:100], flush=True)


def report(h, user, kind, d, o):
    """kind = start | progress | stopped. d = Jellyfin PlaybackStartInfo/ProgressInfo/StopInfo."""
    ci = client_info(h)
    did = ci['device_id'] or ('api-%s' % user[0])
    now = int(time.time())
    psid = _clean(d.get('PlaySessionId') or '', 64) or None
    pos = int((d.get('PositionTicks') or 0) / A.TICKS)
    paused = 1 if d.get('IsPaused') else 0
    with _lock:
        s = _live.setdefault(did, {'id': secrets.token_hex(16), 'user_id': user[0], 'user_name': user[1], 'queue': [], 'last': now})
        s.update(ci, last=now)
        s.setdefault('device_id', did)
        if kind == 'stopped':
            s['play'] = None
        else:
            s['play'] = {'jid': o['jid'], 'mid': o['mid'], 'pos': pos, 'paused': bool(paused), 'muted': bool(d.get('IsMuted')),
                         'volume': d.get('VolumeLevel'), 'audio': d.get('AudioStreamIndex'), 'sub': d.get('SubtitleStreamIndex'),
                         'method': _clean(d.get('PlayMethod') or 'DirectPlay', 20), 'psid': psid, 'at': now,
                         'rate': d.get('PlaybackRate')}
            q = d.get('NowPlayingQueue')
            if isinstance(q, list):
                s['queue'] = [{'Id': A.norm_id(str(x.get('Id') or '')), 'PlaylistItemId': _clean(x.get('PlaylistItemId'), 40)}
                              for x in q[:300] if isinstance(x, dict) and x.get('Id')]
            if d.get('PlaylistItemId'):
                s['playlist_item'] = _clean(d['PlaylistItemId'], 40)
    sid = psid or ('%s-%s' % (did[:40], o['mid']))
    try:
        with S.sqlite_session(S.DATA / 'library.sqlite') as c:
            if kind == 'start':
                c.execute('INSERT OR REPLACE INTO playback_sessions(id,user_id,media_id,device_id,started,last_progress,position,paused,method,stopped) '
                          'VALUES(?,?,?,?,?,?,?,?,?,NULL)', (sid, user[0], o['mid'], did, now, now, pos, paused, _clean(d.get('PlayMethod') or 'DirectPlay', 20)))
            elif kind == 'progress':
                if not c.execute('UPDATE playback_sessions SET last_progress=?,position=?,paused=? WHERE id=?', (now, pos, paused, sid)).rowcount:
                    c.execute('INSERT OR IGNORE INTO playback_sessions(id,user_id,media_id,device_id,started,last_progress,position,paused,method) '
                              'VALUES(?,?,?,?,?,?,?,?,?)', (sid, user[0], o['mid'], did, now, now, pos, paused, 'DirectPlay'))
            else:
                c.execute('UPDATE playback_sessions SET last_progress=?,position=?,stopped=? WHERE id=?', (now, pos, now, sid))
    except Exception as e:
        print('JF Sitzung:', type(e).__name__, str(e)[:100], flush=True)


def sessions(cat, user, sid, q):
    """GET /Sessions – Admin sieht alle Geräte, andere nur ihre eigenen."""
    now = int(time.time())
    want_dev = q.get('deviceid')
    out = []
    with _lock:
        items = [(k, dict(v)) for k, v in _live.items()]
    for did, s in sorted(items, key=lambda x: -x[1].get('last', 0)):
        if now - s.get('last', 0) > ACTIVE:
            continue
        if user[2] != 'admin' and s['user_id'] != user[0]:
            continue
        if want_dev and did != want_dev:
            continue
        x = {'Id': s['id'], 'UserId': A.uid_of(s['user_id']), 'UserName': s.get('user_name') or '', 'Client': s.get('client') or '',
             'DeviceName': s.get('device') or '', 'DeviceId': did, 'ApplicationVersion': s.get('version') or '',
             'LastActivityDate': A.iso(s.get('last', now)), 'LastPlaybackCheckIn': A.iso(s.get('last', now)),
             'RemoteEndPoint': s.get('ip') or '', 'IsActive': True, 'SupportsMediaControl': False, 'SupportsRemoteControl': False,
             'HasCustomDeviceName': False, 'ServerId': sid, 'AdditionalUsers': [], 'PlayableMediaTypes': ['Audio', 'Video'],
             'SupportedCommands': [], 'NowPlayingQueue': s.get('queue') or [], 'NowPlayingQueueFullItems': [],
             'Capabilities': {'PlayableMediaTypes': ['Audio', 'Video'], 'SupportedCommands': [], 'SupportsMediaControl': False,
                              'SupportsPersistentIdentifier': True},
             'PlayState': {'CanSeek': False, 'IsPaused': False, 'IsMuted': False, 'RepeatMode': 'RepeatNone', 'PlaybackOrder': 'Default'}}
        p = s.get('play')
        o = cat['items'].get(p['jid']) if p else None
        if p and o and now - p['at'] < 120:
            pos = p['pos'] + (0 if p['paused'] else now - p['at'])
            x['NowPlayingItem'] = A.dto(cat, o, ({}, set()), sid)
            x['PlayState'].update(PositionTicks=int(pos * A.TICKS), CanSeek=True, IsPaused=p['paused'], IsMuted=p['muted'],
                                  PlayMethod=p['method'], MediaSourceId=o['jid'], PlaySessionId=p['psid'])
            if p.get('volume') is not None:
                x['PlayState']['VolumeLevel'] = p['volume']
            for k, v in (('AudioStreamIndex', p.get('audio')), ('SubtitleStreamIndex', p.get('sub'))):
                if v is not None:
                    x['PlayState'][k] = v
            if s.get('playlist_item'):
                x['PlaylistItemId'] = s['playlist_item']
        out.append(x)
    return out


def devices(user, sid):
    with S.sqlite_session(S.DATA / 'library.sqlite') as c:
        rows = c.execute('SELECT device_id,user_id,user_name,client,device,version,last_seen,custom_name FROM jf_devices '
                         'ORDER BY last_seen DESC LIMIT 200').fetchall()
    items = []
    for did, uid, uname, client, dev, ver, last, custom in rows:
        if user[2] != 'admin' and uid != user[0]:
            continue
        items.append({'Id': did, 'Name': custom or dev or did, 'CustomName': custom, 'AppName': client or '', 'AppVersion': ver or '',
                      'LastUserName': uname or '', 'LastUserId': A.uid_of(uid) if uid else None, 'DateLastActivity': A.iso(last),
                      'Capabilities': {'PlayableMediaTypes': ['Audio', 'Video'], 'SupportedCommands': [], 'SupportsMediaControl': False,
                                       'SupportsPersistentIdentifier': True}, 'IconUrl': None})
    return {'Items': items, 'TotalRecordCount': len(items), 'StartIndex': 0}


def device_info(did):
    with S.sqlite_session(S.DATA / 'library.sqlite') as c:
        r = c.execute('SELECT device_id,client,device,version,custom_name,user_name,last_seen,user_id FROM jf_devices WHERE device_id=?', (did,)).fetchone()
    if not r:
        return None
    return {'Id': r[0], 'Name': r[4] or r[2] or r[0], 'CustomName': r[4], 'AppName': r[1] or '', 'AppVersion': r[3] or '',
            'LastUserName': r[5] or '', 'LastUserId': A.uid_of(r[7]) if r[7] else None, 'DateLastActivity': A.iso(r[6]),
            'Capabilities': {'PlayableMediaTypes': ['Audio', 'Video'], 'SupportedCommands': []}}


def set_name(did, name):
    with S.sqlite_session(S.DATA / 'library.sqlite') as c:
        c.execute('UPDATE jf_devices SET custom_name=? WHERE device_id=?', (_clean(name, 60) or None, did))


def delete_device(did):
    with S.sqlite_session(S.DATA / 'library.sqlite') as c:
        c.execute('DELETE FROM jf_devices WHERE device_id=?', (did,))
    with _lock:
        _live.pop(did, None)


def history(user_id, limit=50):
    with S.sqlite_session(S.DATA / 'library.sqlite') as c:
        return c.execute('SELECT media_id,device_id,started,position,stopped FROM playback_sessions WHERE user_id=? '
                         'ORDER BY started DESC LIMIT ?', (user_id, limit)).fetchall()
