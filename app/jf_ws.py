"""WebSocket /socket wie bei Jellyfin: hält die Verbindung (KeepAlive) und meldet Änderungen live,
z. B. „gesehen“/Favorit auf dem Handy → sofort auch auf dem Fernseher sichtbar."""
import base64
import hashlib
import json
import socket
import struct
import threading
import uuid

GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
MAX_FRAME = 1_000_000
MAX_CONN = 40
_lock = threading.Lock()
_conns = {}   # id -> Conn


class Conn:
    def __init__(self, h, user_id):
        self.h, self.user_id, self.lock = h, user_id, threading.Lock()
        self.alive = True

    def send(self, obj):
        data = json.dumps(obj, separators=(',', ':')).encode('utf-8')
        return self._frame(0x1, data)

    def _frame(self, op, data):
        n = len(data)
        head = bytes([0x80 | op]) + (bytes([n]) if n < 126 else (b'\x7e' + struct.pack('>H', n)) if n < 65536
                                    else (b'\x7f' + struct.pack('>Q', n)))
        try:
            with self.lock:
                self.h.wfile.write(head + data)
                self.h.wfile.flush()
            return True
        except (OSError, ValueError):
            self.alive = False
            return False


def _read_exact(f, n):
    buf = b''
    while len(buf) < n:
        chunk = f.read(n - len(buf))
        if not chunk:
            raise ConnectionError('closed')
        buf += chunk
    return buf


def _read_frame(f):
    b1, b2 = _read_exact(f, 2)
    op, masked, n = b1 & 0x0F, b2 & 0x80, b2 & 0x7F
    if n == 126:
        n = struct.unpack('>H', _read_exact(f, 2))[0]
    elif n == 127:
        n = struct.unpack('>Q', _read_exact(f, 8))[0]
    if n > MAX_FRAME:
        raise ConnectionError('frame too large')
    mask = _read_exact(f, 4) if masked else b'\0\0\0\0'
    data = bytearray(_read_exact(f, n))
    for i in range(n):
        data[i] ^= mask[i % 4]
    return op, bytes(data)


def serve(h, user_id):
    """Übernimmt die HTTP-Verbindung als WebSocket. Gibt True zurück (Anfrage beantwortet)."""
    key = h.headers.get('Sec-WebSocket-Key', '')
    if 'websocket' not in (h.headers.get('Upgrade') or '').lower() or not key:
        h.send(400, b'{"error":"WEBSOCKET_REQUIRED"}', 'application/json', {})
        return True
    with _lock:
        if len(_conns) >= MAX_CONN:
            h.send(503, b'{"error":"TOO_MANY_CONNECTIONS"}', 'application/json', {})
            return True
    accept = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
    h.send_response(101, 'Switching Protocols')
    h.send_header('Upgrade', 'websocket')
    h.send_header('Connection', 'Upgrade')
    h.send_header('Sec-WebSocket-Accept', accept)
    h.end_headers()
    h.wfile.flush()
    h.close_connection = True
    try:
        h.connection.settimeout(150)   # Clients senden alle ~30 s ein KeepAlive
    except OSError:
        pass
    c = Conn(h, user_id)
    cid = uuid.uuid4().hex
    with _lock:
        _conns[cid] = c
    try:
        c.send({'MessageType': 'ForceKeepAlive', 'Data': 60, 'MessageId': uuid.uuid4().hex})
        while c.alive:
            op, data = _read_frame(h.rfile)
            if op == 0x8:            # schließen
                c._frame(0x8, data[:2])
                break
            if op == 0x9:            # Ping -> Pong
                c._frame(0xA, data)
                continue
            if op != 0x1:
                continue
            try:
                msg = json.loads(data.decode('utf-8'))
            except ValueError:
                continue
            t = msg.get('MessageType')
            if t == 'KeepAlive':
                c.send({'MessageType': 'KeepAlive', 'MessageId': uuid.uuid4().hex})
            # SessionsStart/ScheduledTasksInfoStart usw. werden still angenommen
    except (ConnectionError, socket.timeout, OSError, ValueError):
        pass
    finally:
        c.alive = False
        with _lock:
            _conns.pop(cid, None)
    return True


def broadcast(user_id, obj):
    """Nachricht an alle offenen Verbindungen eines Nutzers (user_id=None: an alle)."""
    with _lock:
        targets = [c for c in _conns.values() if user_id is None or c.user_id == user_id]
    for c in targets:
        if not c.send(dict(obj, MessageId=uuid.uuid4().hex)):
            try:
                c.h.connection.close()
            except OSError:
                pass


def count():
    with _lock:
        return len(_conns)
