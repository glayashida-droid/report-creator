"""Byte-mode QR Code (ECC M). No third-party QR package."""

from __future__ import annotations

import io
from typing import List, Sequence

from PIL import Image

# version -> (ecc_per_block, g1_blocks, g1_data, g2_blocks, g2_data)
_M_BLOCKS = {
    1: (10, 1, 16, 0, 0),
    2: (16, 1, 28, 0, 0),
    3: (26, 1, 44, 0, 0),
    4: (18, 2, 32, 0, 0),
    5: (24, 2, 43, 0, 0),
    6: (16, 4, 27, 0, 0),
    7: (18, 4, 31, 0, 0),
    8: (22, 2, 38, 2, 39),
    9: (22, 3, 36, 2, 37),
    10: (26, 4, 43, 1, 44),
}

_ALIGN = {
    1: (),
    2: (6, 18),
    3: (6, 22),
    4: (6, 26),
    5: (6, 30),
    6: (6, 34),
    7: (6, 22, 38),
    8: (6, 24, 42),
    9: (6, 26, 46),
    10: (6, 28, 50),
}

_REMAINDER = {1: 0, **{v: 7 for v in range(2, 7)}, **{v: 0 for v in range(7, 11)}}


def _gf_tables():
    exp = [0] * 512
    log = [0] * 256
    x = 1
    for i in range(255):
        exp[i] = x
        log[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    for i in range(255, 512):
        exp[i] = exp[i - 255]
    return exp, log


_EXP, _LOG = _gf_tables()


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _rs_divisor(degree: int) -> List[int]:
    poly = [1]
    for i in range(degree):
        nxt = [0] * (len(poly) + 1)
        for j, coef in enumerate(poly):
            nxt[j] ^= coef
            nxt[j + 1] ^= _gf_mul(coef, _EXP[i])
        poly = nxt
    return poly


def _rs_remainder(data: Sequence[int], degree: int) -> List[int]:
    gen = _rs_divisor(degree)
    ecc = [0] * degree
    for byte in data:
        factor = byte ^ ecc[0]
        ecc = ecc[1:] + [0]
        if factor == 0:
            continue
        for i in range(degree):
            ecc[i] ^= _gf_mul(gen[i + 1], factor)
    return ecc


def _data_capacity(version: int) -> int:
    ecc, g1, d1, g2, d2 = _M_BLOCKS[version]
    return g1 * d1 + g2 * d2


def _cc_bits(version: int) -> int:
    return 8 if version < 10 else 16


def _bit_list(value: int, width: int) -> List[int]:
    return [(value >> (width - 1 - i)) & 1 for i in range(width)]


def _encode_bits(data: bytes, version: int) -> List[int]:
    capacity = _data_capacity(version) * 8
    bits: List[int] = []
    bits.extend(_bit_list(0b0100, 4))
    bits.extend(_bit_list(len(data), _cc_bits(version)))
    for byte in data:
        bits.extend(_bit_list(byte, 8))
    remain = capacity - len(bits)
    bits.extend([0] * min(4, remain))
    while len(bits) % 8:
        bits.append(0)
    pad = (0xEC, 0x11)
    i = 0
    while len(bits) + 8 <= capacity:
        bits.extend(_bit_list(pad[i % 2], 8))
        i += 1
    if len(bits) < capacity:
        bits.extend([0] * (capacity - len(bits)))
    return bits[:capacity]


def _bits_to_bytes(bits: Sequence[int]) -> List[int]:
    out = []
    for i in range(0, len(bits), 8):
        n = 0
        for b in bits[i : i + 8]:
            n = (n << 1) | b
        out.append(n)
    return out


def _interleave(data_bytes: Sequence[int], version: int) -> List[int]:
    ecc_n, g1, d1, g2, d2 = _M_BLOCKS[version]
    blocks: List[List[int]] = []
    eccs: List[List[int]] = []
    offset = 0
    for _ in range(g1):
        block = list(data_bytes[offset : offset + d1])
        offset += d1
        blocks.append(block)
        eccs.append(_rs_remainder(block, ecc_n))
    for _ in range(g2):
        block = list(data_bytes[offset : offset + d2])
        offset += d2
        blocks.append(block)
        eccs.append(_rs_remainder(block, ecc_n))
    out: List[int] = []
    for i in range(max(d1, d2)):
        for block in blocks:
            if i < len(block):
                out.append(block[i])
    for i in range(ecc_n):
        for ecc in eccs:
            out.append(ecc[i])
    return out


def _bytes_to_bits(values: Sequence[int], extra: int) -> List[int]:
    bits: List[int] = []
    for value in values:
        bits.extend(_bit_list(value, 8))
    bits.extend([0] * extra)
    return bits


def _size(version: int) -> int:
    return 21 + 4 * (version - 1)


def _blank(version: int):
    n = _size(version)
    grid = [[0] * n for _ in range(n)]
    locked = [[False] * n for _ in range(n)]
    return grid, locked


def _fill(grid, locked, x, y, bit: int) -> None:
    grid[y][x] = bit
    locked[y][x] = True


def _finder(grid, locked, left: int, top: int) -> None:
    pattern = (
        (1, 1, 1, 1, 1, 1, 1),
        (1, 0, 0, 0, 0, 0, 1),
        (1, 0, 1, 1, 1, 0, 1),
        (1, 0, 1, 1, 1, 0, 1),
        (1, 0, 1, 1, 1, 0, 1),
        (1, 0, 0, 0, 0, 0, 1),
        (1, 1, 1, 1, 1, 1, 1),
    )
    for dy, row in enumerate(pattern):
        for dx, bit in enumerate(row):
            _fill(grid, locked, left + dx, top + dy, bit)
    n = len(grid)
    for y in range(top - 1, top + 8):
        for x in range(left - 1, left + 8):
            if 0 <= x < n and 0 <= y < n and not locked[y][x]:
                _fill(grid, locked, x, y, 0)


def _alignment(grid, locked, cx: int, cy: int) -> None:
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            bit = 0 if max(abs(dx), abs(dy)) == 1 else 1
            _fill(grid, locked, cx + dx, cy + dy, bit)


def _place_function(grid, locked, version: int) -> None:
    n = len(grid)
    _finder(grid, locked, 0, 0)
    _finder(grid, locked, n - 7, 0)
    _finder(grid, locked, 0, n - 7)
    for pos in range(8, n - 8):
        bit = 1 if pos % 2 == 0 else 0
        _fill(grid, locked, pos, 6, bit)
        _fill(grid, locked, 6, pos, bit)
    centers = _ALIGN[version]
    for cy in centers:
        for cx in centers:
            if (cx < 9 and cy < 9) or (cx < 9 and cy > n - 10) or (cx > n - 10 and cy < 9):
                continue
            _alignment(grid, locked, cx, cy)
    _fill(grid, locked, 8, n - 8, 1)
    for i in range(9):
        if not locked[8][i]:
            locked[8][i] = True
        if not locked[i][8]:
            locked[i][8] = True
    for i in range(8):
        locked[8][n - 1 - i] = True
        locked[n - 1 - i][8] = True
    locked[8][n - 8] = True
    if version >= 7:
        for i in range(6):
            for j in range(3):
                locked[n - 11 + j][i] = True
                locked[i][n - 11 + j] = True


def _mask_bit(mask: int, x: int, y: int) -> int:
    if mask == 0:
        return int((x + y) % 2 == 0)
    if mask == 1:
        return int(y % 2 == 0)
    if mask == 2:
        return int(x % 3 == 0)
    if mask == 3:
        return int((x + y) % 3 == 0)
    if mask == 4:
        return int((y // 2 + x // 3) % 2 == 0)
    if mask == 5:
        return int((x * y) % 2 + (x * y) % 3 == 0)
    if mask == 6:
        return int(((x * y) % 2 + (x * y) % 3) % 2 == 0)
    return int(((x + y) % 2 + (x * y) % 3) % 2 == 0)


def _place_data(grid, locked, bits: Sequence[int], mask: int) -> None:
    n = len(grid)
    i = 0
    upward = True
    x = n - 1
    while x > 0:
        if x == 6:
            x -= 1
        ys = range(n - 1, -1, -1) if upward else range(n)
        for y in ys:
            for dx in (0, -1):
                xx = x + dx
                if locked[y][xx]:
                    continue
                bit = bits[i] if i < len(bits) else 0
                i += 1
                grid[y][xx] = bit ^ _mask_bit(mask, xx, y)
        upward = not upward
        x -= 2


def _bch_format(five: int) -> int:
    rem = five
    for _ in range(10):
        rem = (rem << 1) ^ (0x537 if (rem >> 9) & 1 else 0)
    return ((five << 10) | rem) ^ 0x5412


def _bch_version(version: int) -> int:
    rem = version
    for _ in range(12):
        rem = (rem << 1) ^ (0x1F25 if (rem >> 11) & 1 else 0)
    return (version << 12) | rem


def _draw_format(grid, locked, mask: int) -> None:
    n = len(grid)
    bits = _bch_format(mask)  # ECC M = 00, so five bits are 00mmm
    coords_a = [
        (8, 0), (8, 1), (8, 2), (8, 3), (8, 4), (8, 5), (8, 7), (8, 8),
        (7, 8), (5, 8), (4, 8), (3, 8), (2, 8), (1, 8), (0, 8),
    ]
    coords_b = [
        (n - 1, 8), (n - 2, 8), (n - 3, 8), (n - 4, 8), (n - 5, 8), (n - 6, 8),
        (n - 7, 8), (n - 8, 8),
        (8, n - 7), (8, n - 6), (8, n - 5), (8, n - 4), (8, n - 3), (8, n - 2),
        (8, n - 1),
    ]
    for i in range(15):
        bit = (bits >> i) & 1
        x, y = coords_a[i]
        grid[y][x] = bit
        locked[y][x] = True
        x, y = coords_b[i]
        grid[y][x] = bit
        locked[y][x] = True
    grid[n - 8][8] = 1
    locked[n - 8][8] = True


def _draw_version(grid, locked, version: int) -> None:
    if version < 7:
        return
    n = len(grid)
    bits = _bch_version(version)
    k = 0
    for a in range(6):
        for b in range(3):
            bit = (bits >> k) & 1
            k += 1
            grid[n - 11 + b][a] = bit
            grid[a][n - 11 + b] = bit
            locked[n - 11 + b][a] = True
            locked[a][n - 11 + b] = True


def _penalty(grid) -> int:
    n = len(grid)
    score = 0
    for y in range(n):
        run = 1
        for x in range(1, n):
            if grid[y][x] == grid[y][x - 1]:
                run += 1
            else:
                if run >= 5:
                    score += run - 2
                run = 1
        if run >= 5:
            score += run - 2
    for x in range(n):
        run = 1
        for y in range(1, n):
            if grid[y][x] == grid[y - 1][x]:
                run += 1
            else:
                if run >= 5:
                    score += run - 2
                run = 1
        if run >= 5:
            score += run - 2
    for y in range(n - 1):
        for x in range(n - 1):
            if grid[y][x] == grid[y][x + 1] == grid[y + 1][x] == grid[y + 1][x + 1]:
                score += 3
    pattern = (1, 0, 1, 1, 1, 0, 1)
    for y in range(n):
        row = grid[y]
        for x in range(n - 6):
            if tuple(row[x : x + 7]) == pattern:
                left = x >= 4 and all(v == 0 for v in row[x - 4 : x])
                right = x + 10 <= n and all(v == 0 for v in row[x + 7 : x + 11])
                if left or right:
                    score += 40
    for x in range(n):
        col = [grid[y][x] for y in range(n)]
        for y in range(n - 6):
            if tuple(col[y : y + 7]) == pattern:
                up = y >= 4 and all(v == 0 for v in col[y - 4 : y])
                down = y + 10 <= n and all(v == 0 for v in col[y + 7 : y + 11])
                if up or down:
                    score += 40
    dark = sum(sum(row) for row in grid)
    percent = (dark * 100) // (n * n)
    score += (abs(percent - 50) // 5) * 10
    return score


def _choose_version(payload: bytes) -> int:
    for version in range(1, 11):
        header = 4 + _cc_bits(version)
        need = header + 8 * len(payload) + 4
        if need <= _data_capacity(version) * 8:
            return version
    raise ValueError("内容过长，放不进二维码")


def make_matrix(text: str) -> List[List[int]]:
    payload = text.encode("utf-8")
    version = _choose_version(payload)
    data_bits = _encode_bits(payload, version)
    interleaved = _interleave(_bits_to_bytes(data_bits), version)
    bits = _bytes_to_bits(interleaved, _REMAINDER[version])
    best = None
    best_score = None
    for mask in range(8):
        grid, locked = _blank(version)
        _place_function(grid, locked, version)
        _place_data(grid, locked, bits, mask)
        _draw_format(grid, locked, mask)
        _draw_version(grid, locked, version)
        score = _penalty(grid)
        if best_score is None or score < best_score:
            best_score = score
            best = grid
    assert best is not None
    return best


def png_bytes(text: str, module_px: int = 8, border: int = 4) -> bytes:
    matrix = make_matrix(text)
    n = len(matrix)
    size = (n + 2 * border) * module_px
    img = Image.new("RGB", (size, size), (255, 255, 255))
    pix = img.load()
    for y, row in enumerate(matrix):
        for x, bit in enumerate(row):
            if not bit:
                continue
            x0 = (x + border) * module_px
            y0 = (y + border) * module_px
            for dy in range(module_px):
                for dx in range(module_px):
                    pix[x0 + dx, y0 + dy] = (0, 0, 0)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()
