"""Read video width/height from container headers without ffprobe (Python stdlib only).

Supported: MP4/M4V/MOV (ISO BMFF), MKV/WebM (EBML), AVI (RIFF).
Returns (width, height) or (None, None) if the resolution cannot be determined;
callers keep treating unknown resolution as blocked.
"""
import struct

MAX_BOXES = 20000
MKV_SCAN_LIMIT = 16 * 1024 * 1024


def probe(path):
    try:
        with open(str(path), 'rb') as f:
            head = f.read(16)
            if len(head) < 12:
                return None, None
            if head[:4] == b'\x1a\x45\xdf\xa3':
                return _mkv(f)
            if head[:4] == b'RIFF' and head[8:12] == b'AVI ':
                return _avi(f)
            if head[4:8] in (b'ftyp', b'moov', b'mdat', b'free', b'wide', b'skip', b'pnot'):
                return _mp4(f)
    except (OSError, ValueError, struct.error):
        pass
    return None, None


# ---------- MP4 / MOV ----------
def _boxes(f, start, end):
    pos, n = start, 0
    while pos + 8 <= end and n < MAX_BOXES:
        n += 1
        f.seek(pos)
        hdr = f.read(8)
        if len(hdr) < 8:
            return
        size, kind = struct.unpack('>I4s', hdr)
        header = 8
        if size == 1:
            big = f.read(8)
            if len(big) < 8:
                return
            size = struct.unpack('>Q', big)[0]
            header = 16
        elif size == 0:
            size = end - pos
        if size < header:
            return
        yield kind, pos + header, min(pos + size, end)
        pos += size


def _mp4(f):
    f.seek(0, 2)
    end = f.tell()
    for kind, s, e in _boxes(f, 0, end):
        if kind == b'moov':
            return _moov(f, s, e)
    return None, None


def _moov(f, s, e):
    best = (None, None)
    for kind, ts, te in _boxes(f, s, e):
        if kind != b'trak':
            continue
        is_video, dims = False, (None, None)
        for k2, s2, e2 in _boxes(f, ts, te):
            if k2 == b'tkhd':
                dims = _tkhd(f, s2, e2)
            elif k2 == b'mdia':
                for k3, s3, e3 in _boxes(f, s2, e2):
                    if k3 == b'hdlr':
                        f.seek(s3 + 8)
                        is_video = f.read(4) == b'vide'
        w, h = dims
        if is_video and w and h:
            if best[0] is None or w * h > best[0] * best[1]:
                best = (w, h)
    return best


def _tkhd(f, s, e):
    f.seek(s)
    version = f.read(1)
    if not version:
        return None, None
    # width/height (16.16 fixed point) follow the 3x3 matrix:
    # byte offset 76 in a version-0 tkhd, 88 in a version-1 tkhd
    f.seek(s + (88 if version[0] == 1 else 76))
    data = f.read(8)
    if len(data) < 8:
        return None, None
    w, h = struct.unpack('>II', data)
    w, h = w >> 16, h >> 16
    return (w, h) if w and h else (None, None)


# ---------- MKV / WebM ----------
def _vint(f, keep_marker):
    first = f.read(1)
    if not first:
        raise ValueError('eof')
    b = first[0]
    length = 1
    mask = 0x80
    while length <= 8 and not (b & mask):
        mask >>= 1
        length += 1
    if length > 8:
        raise ValueError('bad vint')
    value = b if keep_marker else b & (mask - 1)
    rest = f.read(length - 1)
    if len(rest) != length - 1:
        raise ValueError('eof')
    for x in rest:
        value = (value << 8) | x
    unknown = (not keep_marker) and value == (1 << (7 * length)) - 1
    return value, length, unknown


SEGMENT, TRACKS, TRACK_ENTRY, VIDEO, CLUSTER = 0x18538067, 0x1654AE6B, 0xAE, 0xE0, 0x1F43B675
PIXEL_W, PIXEL_H, TRACK_TYPE = 0xB0, 0xBA, 0x83


def _mkv(f):
    f.seek(0, 2)
    end = min(f.tell(), MKV_SCAN_LIMIT)
    f.seek(0)
    best = (None, None)
    pos = 0
    while pos < end:
        f.seek(pos)
        eid, _, _ = _vint(f, True)
        size, _, unknown = _vint(f, False)
        data = f.tell()
        if eid == SEGMENT:
            seg_end = end if unknown else min(data + size, end)
            return _mkv_segment(f, data, seg_end)
        if unknown:
            break
        pos = data + size
    return best


def _mkv_children(f, start, end):
    pos = start
    while pos < end:
        f.seek(pos)
        try:
            eid, _, _ = _vint(f, True)
            size, _, unknown = _vint(f, False)
        except ValueError:
            return
        data = f.tell()
        stop = end if unknown else min(data + size, end)
        yield eid, data, stop
        if unknown:
            return
        pos = data + size


def _uint(f, s, e):
    f.seek(s)
    raw = f.read(max(0, min(e - s, 8)))
    v = 0
    for x in raw:
        v = (v << 8) | x
    return v


def _mkv_segment(f, start, end):
    best = (None, None)
    for eid, s, e in _mkv_children(f, start, end):
        if eid == CLUSTER:
            break
        if eid != TRACKS:
            continue
        for tid, ts, te in _mkv_children(f, s, e):
            if tid != TRACK_ENTRY:
                continue
            w = h = None
            ttype = None
            for cid, cs, ce in _mkv_children(f, ts, te):
                if cid == TRACK_TYPE:
                    ttype = _uint(f, cs, ce)
                elif cid == VIDEO:
                    for vid, vs, ve in _mkv_children(f, cs, ce):
                        if vid == PIXEL_W:
                            w = _uint(f, vs, ve)
                        elif vid == PIXEL_H:
                            h = _uint(f, vs, ve)
            if ttype in (None, 1) and w and h:
                if best[0] is None or w * h > best[0] * best[1]:
                    best = (w, h)
        if best[0]:
            return best
    return best


# ---------- AVI ----------
def _avi(f):
    f.seek(12)
    data = f.read(65536)
    i = data.find(b'avih')
    if i < 0 or i + 8 + 40 > len(data):
        return None, None
    body = data[i + 8:i + 8 + 40]
    w, h = struct.unpack('<II', body[32:40])
    return (w, h) if w and h else (None, None)


# ---------- Laufzeit + Codecs (für die Jellyfin-Oberfläche) ----------
_MP4_CODECS = {b'avc1': 'h264', b'avc3': 'h264', b'hev1': 'hevc', b'hvc1': 'hevc', b'mp4v': 'mpeg4', b'av01': 'av1',
               b'vp09': 'vp9', b'mp4a': 'aac', b'ac-3': 'ac3', b'ec-3': 'eac3', b'Opus': 'opus', b'fLaC': 'flac', b'.mp3': 'mp3'}
_MKV_CODECS = {'V_MPEG4/ISO/AVC': 'h264', 'V_MPEGH/ISO/HEVC': 'hevc', 'V_VP9': 'vp9', 'V_VP8': 'vp8', 'V_AV1': 'av1',
               'V_MPEG4/ISO/ASP': 'mpeg4', 'A_AAC': 'aac', 'A_AC3': 'ac3', 'A_EAC3': 'eac3', 'A_DTS': 'dts', 'A_OPUS': 'opus',
               'A_VORBIS': 'vorbis', 'A_FLAC': 'flac', 'A_MPEG/L3': 'mp3', 'A_TRUEHD': 'truehd', 'S_TEXT/UTF8': 'subrip',
               'S_TEXT/ASS': 'ass', 'S_TEXT/SSA': 'ssa', 'S_HDMV/PGS': 'pgssub', 'S_VOBSUB': 'dvdsub'}


def details(path):
    """{'duration': Sekunden oder None, 'streams': [{'type','codec','language','title','default'}]}"""
    out = {'duration': None, 'streams': []}
    try:
        with open(str(path), 'rb') as f:
            head = f.read(16)
            if head[:4] == b'\x1a\x45\xdf\xa3':
                _mkv_details(f, out)
            elif head[4:8] in (b'ftyp', b'moov', b'mdat', b'free', b'wide', b'skip', b'pnot'):
                _mp4_details(f, out)
    except (OSError, ValueError, struct.error):
        pass
    return out


def _mp4_details(f, out):
    f.seek(0, 2)
    end = f.tell()
    for kind, s, e in _boxes(f, 0, end):
        if kind != b'moov':
            continue
        for k, ks, ke in _boxes(f, s, e):
            if k == b'mvhd':
                f.seek(ks)
                v = f.read(1)[0]
                if v == 1:
                    f.seek(ks + 20); ts, dur = struct.unpack('>IQ', f.read(12))
                else:
                    f.seek(ks + 12); ts, dur = struct.unpack('>II', f.read(8))
                if ts:
                    out['duration'] = dur / ts
            elif k == b'trak':
                st = {'type': None, 'codec': None, 'language': 'und', 'title': '', 'default': True}
                for k2, s2, e2 in _boxes(f, ks, ke):
                    if k2 != b'mdia':
                        continue
                    for k3, s3, e3 in _boxes(f, s2, e2):
                        if k3 == b'hdlr':
                            f.seek(s3 + 8); t = f.read(4)
                            st['type'] = {b'vide': 'Video', b'soun': 'Audio', b'sbtl': 'Subtitle', b'text': 'Subtitle', b'subt': 'Subtitle'}.get(t)
                        elif k3 == b'mdhd':
                            f.seek(s3); v = f.read(1)[0]
                            f.seek(s3 + (32 if v == 1 else 20)); lang = struct.unpack('>H', f.read(2))[0]
                            code = ''.join(chr(((lang >> sh) & 31) + 0x60) for sh in (10, 5, 0))
                            if code.isalpha():
                                st['language'] = code
                        elif k3 == b'minf':
                            for k4, s4, e4 in _boxes(f, s3, e3):
                                if k4 != b'stbl':
                                    continue
                                for k5, s5, e5 in _boxes(f, s4, e4):
                                    if k5 == b'stsd':
                                        f.seek(s5 + 12); fmt = f.read(4)
                                        st['codec'] = _MP4_CODECS.get(fmt, fmt.decode('latin-1').strip().lower())
                if st['type']:
                    out['streams'].append(st)
        return


INFO, TIMESCALE, DURATION, CODEC_ID, LANGUAGE, NAME, FLAG_DEFAULT, FLAG_FORCED = 0x1549A966, 0x2AD7B1, 0x4489, 0x86, 0x22B59C, 0x536E, 0x88, 0x55AA


def _mkv_details(f, out):
    f.seek(0, 2)
    end = min(f.tell(), MKV_SCAN_LIMIT)
    pos = 0
    while pos < end:
        f.seek(pos)
        eid, _, _ = _vint(f, True)
        size, _, unknown = _vint(f, False)
        data = f.tell()
        if eid == SEGMENT:
            seg_end = end if unknown else min(data + size, end)
            scale, dur = 1000000, None
            for cid, s, e in _mkv_children(f, data, seg_end):
                if cid == CLUSTER:
                    break
                if cid == INFO:
                    for iid, s2, e2 in _mkv_children(f, s, e):
                        if iid == TIMESCALE:
                            scale = _uint(f, s2, e2) or scale
                        elif iid == DURATION:
                            f.seek(s2); raw = f.read(e2 - s2)
                            dur = struct.unpack('>d', raw)[0] if len(raw) == 8 else struct.unpack('>f', raw)[0] if len(raw) == 4 else None
                elif cid == TRACKS:
                    for tid, ts, te in _mkv_children(f, s, e):
                        if tid != TRACK_ENTRY:
                            continue
                        st = {'type': None, 'codec': None, 'language': 'eng', 'title': '', 'default': True}
                        for c2, cs, ce in _mkv_children(f, ts, te):
                            if c2 == TRACK_TYPE:
                                st['type'] = {1: 'Video', 2: 'Audio', 17: 'Subtitle'}.get(_uint(f, cs, ce))
                            elif c2 in (CODEC_ID, LANGUAGE, NAME):
                                f.seek(cs); txt = f.read(min(ce - cs, 200)).rstrip(b'\0').decode('utf-8', 'replace')
                                if c2 == CODEC_ID:
                                    st['codec'] = _MKV_CODECS.get(txt, txt.split('/')[-1].lower())
                                elif c2 == LANGUAGE:
                                    st['language'] = txt
                                else:
                                    st['title'] = txt
                            elif c2 == FLAG_DEFAULT:
                                st['default'] = bool(_uint(f, cs, ce))
                            elif c2 == FLAG_FORCED:
                                st['forced'] = bool(_uint(f, cs, ce))
                        if st['type']:
                            out['streams'].append(st)
            if dur:
                out['duration'] = dur * scale / 1e9
            return
        if unknown:
            break
        pos = data + size
