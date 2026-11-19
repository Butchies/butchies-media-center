"""Local QR SVG generator in pure Python (no qrcode/Pillow package, no network).

Byte mode, error correction level M, versions 1-10 (up to 213 bytes),
mask chosen by the standard ISO/IEC 18004 penalty rules.
"""

# (ec codewords per block, [(blocks, data codewords per block), ...]) for level M
_M = {1: (10, [(1, 16)]), 2: (16, [(1, 28)]), 3: (26, [(1, 44)]), 4: (18, [(2, 32)]),
      5: (24, [(2, 43)]), 6: (16, [(4, 27)]), 7: (18, [(4, 31)]), 8: (22, [(2, 38), (2, 39)]),
      9: (22, [(3, 36), (2, 37)]), 10: (26, [(4, 43), (1, 44)])}
_ALIGN = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34],
          7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50]}

_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x; _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100: _x ^= 0x11D
for _i in range(255, 512): _EXP[_i] = _EXP[_i - 255]


def _gmul(a, b):
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


def _rs_ec(data, n):
    gen = [1]
    for i in range(n):
        nxt = [0] * (len(gen) + 1)
        for j, g in enumerate(gen):
            nxt[j] ^= g
            nxt[j + 1] ^= _gmul(g, _EXP[i])
        gen = nxt
    rem = list(data) + [0] * n
    for i in range(len(data)):
        coef = rem[i]
        if coef:
            for j in range(1, len(gen)):
                rem[i + j] ^= _gmul(gen[j], coef)
    return rem[len(data):]


def _bch(value, poly, bits):
    v = value << bits
    plen = poly.bit_length()
    while v.bit_length() >= plen:
        v ^= poly << (v.bit_length() - plen)
    return (value << bits) | v


def _codewords(data, version):
    ec, groups = _M[version]
    capacity = sum(b * d for b, d in groups)
    bits = [0, 1, 0, 0]
    count_bits = 8 if version < 10 else 16
    bits += [(len(data) >> i) & 1 for i in range(count_bits - 1, -1, -1)]
    for byte in data:
        bits += [(byte >> i) & 1 for i in range(7, -1, -1)]
    bits += [0] * min(4, capacity * 8 - len(bits))
    bits += [0] * (-len(bits) % 8)
    words = [int(''.join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = 0
    while len(words) < capacity:
        words.append((0xEC, 0x11)[pad % 2]); pad += 1
    blocks, pos = [], 0
    for count, size in groups:
        for _ in range(count):
            blocks.append(words[pos:pos + size]); pos += size
    ecs = [_rs_ec(b, ec) for b in blocks]
    out = []
    for i in range(max(len(b) for b in blocks)):
        out += [b[i] for b in blocks if i < len(b)]
    for i in range(ec):
        out += [e[i] for e in ecs]
    return out


def _base(version):
    size = 17 + 4 * version
    m = [[None] * size for _ in range(size)]

    def finder(r, c):
        for dr in range(-1, 8):
            for dc in range(-1, 8):
                rr, cc = r + dr, c + dc
                if 0 <= rr < size and 0 <= cc < size:
                    inside = 0 <= dr <= 6 and 0 <= dc <= 6
                    ring = inside and (dr in (0, 6) or dc in (0, 6))
                    core = 2 <= dr <= 4 and 2 <= dc <= 4
                    m[rr][cc] = 1 if (ring or core) else 0
    finder(0, 0); finder(0, size - 7); finder(size - 7, 0)
    for i in range(8, size - 8):
        m[6][i] = m[i][6] = 1 if i % 2 == 0 else 0
    pos = _ALIGN[version]
    corners = {(pos[0], pos[0]), (pos[0], pos[-1]), (pos[-1], pos[0])} if pos else set()
    for r in pos:
        for c in pos:
            if (r, c) in corners:
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    m[r + dr][c + dc] = 1 if max(abs(dr), abs(dc)) != 1 else 0
    m[size - 8][8] = 1  # dark module
    # reserve format areas
    for i in range(9):
        if m[8][i] is None: m[8][i] = 0
        if m[i][8] is None: m[i][8] = 0
    for i in range(8):
        if m[8][size - 1 - i] is None: m[8][size - 1 - i] = 0
        if m[size - 1 - i][8] is None: m[size - 1 - i][8] = 0
    if version >= 7:
        info = _bch(version, 0x1F25, 12)
        for i in range(18):
            bit = (info >> i) & 1
            m[size - 11 + i % 3][i // 3] = bit
            m[i // 3][size - 11 + i % 3] = bit
    return m


_MASKS = [lambda r, c: (r + c) % 2 == 0, lambda r, c: r % 2 == 0, lambda r, c: c % 3 == 0,
          lambda r, c: (r + c) % 3 == 0, lambda r, c: (r // 2 + c // 3) % 2 == 0,
          lambda r, c: (r * c) % 2 + (r * c) % 3 == 0, lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0,
          lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0]


def _place(base, words, mask):
    size = len(base)
    m = [row[:] for row in base]
    bits = [(w >> i) & 1 for w in words for i in range(7, -1, -1)]
    idx, upward, col = 0, True, size - 1
    while col > 0:
        if col == 6: col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for r in rows:
            for c in (col, col - 1):
                if base[r][c] is None:
                    bit = bits[idx] if idx < len(bits) else 0
                    idx += 1
                    m[r][c] = bit ^ (1 if _MASKS[mask](r, c) else 0)
        upward = not upward
        col -= 2
    fmt = _bch((0b00 << 3) | mask, 0x537, 10) ^ 0x5412
    for i in range(15):
        bit = (fmt >> i) & 1
        # first copy, around the top-left finder
        if i < 6: m[i][8] = bit
        elif i == 6: m[7][8] = bit
        elif i == 7: m[8][8] = bit
        elif i == 8: m[8][7] = bit
        else: m[8][14 - i] = bit
        # second copy, split between top-right and bottom-left finders
        if i < 8: m[8][size - 1 - i] = bit
        else: m[size - 15 + i][8] = bit
    m[size - 8][8] = 1
    return m


def _penalty(m):
    size = len(m); score = 0
    for lines in (m, list(zip(*m))):
        for line in lines:
            run, prev = 0, None
            for v in line:
                if v == prev: run += 1
                else:
                    if run >= 5: score += run - 2
                    run, prev = 1, v
            if run >= 5: score += run - 2
            s = ''.join(map(str, line))
            score += 40 * (s.count('10111010000') + s.count('00001011101'))
    for r in range(size - 1):
        for c in range(size - 1):
            if m[r][c] == m[r + 1][c] == m[r][c + 1] == m[r + 1][c + 1]: score += 3
    dark = sum(map(sum, m))
    score += 10 * (abs(dark * 20 - size * size * 10) // (size * size))
    return score


def matrix_for_bytes(data):
    for version in range(1, 11):
        ec, groups = _M[version]
        capacity = sum(b * d for b, d in groups)
        header = 4 + (8 if version < 10 else 16)
        if header + 8 * len(data) <= capacity * 8:
            break
    else:
        raise ValueError("QR text too long")
    words = _codewords(data, version)
    base = _base(version)
    best = min((_place(base, words, k) for k in range(8)), key=_penalty)
    return best


def svg_for_text(value):
    if len(value) > 512:
        raise ValueError("QR text too long")
    matrix = matrix_for_bytes(value.encode('utf-8'))
    border = 4
    size = len(matrix) + 2 * border
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" role="img" aria-label="QR-Code">',
             f'<rect width="{size}" height="{size}" fill="#fff"/>']
    for y, row in enumerate(matrix):
        for x, filled in enumerate(row):
            if filled:
                parts.append(f'<rect x="{x + border}" y="{y + border}" width="1" height="1" fill="#101828"/>')
    parts.append('</svg>')
    return ''.join(parts).encode('ascii')
