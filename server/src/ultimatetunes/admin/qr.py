# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""A small QR code encoder (ISO/IEC 18004) for the "connect the app" code of the admin panel.

No QR library is approved (SPEC §6), and the panel loads nothing from outside, so the code is
built here and rendered as inline SVG. Only what the panel needs: **byte mode**, error
correction level **M**, versions 1 to 10 (up to 213 bytes, more than a server URL plus an API
key). The mask with the lowest penalty score is chosen, as the standard asks.
"""

from dataclasses import dataclass

from markupsafe import Markup

# Error correction level M: (codewords of EC per block, [(blocks, data codewords per block)]).
_BLOCKS_M: dict[int, tuple[int, tuple[tuple[int, int], ...]]] = {
    1: (10, ((1, 16),)),
    2: (16, ((1, 28),)),
    3: (26, ((1, 44),)),
    4: (18, ((2, 32),)),
    5: (24, ((2, 43),)),
    6: (16, ((4, 27),)),
    7: (18, ((4, 31),)),
    8: (22, ((2, 38), (2, 39))),
    9: (22, ((3, 36), (2, 37))),
    10: (26, ((4, 43), (1, 44))),
}
_ALIGNMENT: dict[int, tuple[int, ...]] = {
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
MAX_VERSION = 10
# Format bits of level M (ISO/IEC 18004 table 12: L=01, M=00, Q=11, H=10).
_ECL_M = 0b00
_MODE_BYTE = 0b0100
QUIET_ZONE = 4


class QrTooLongError(ValueError):
    """The text does not fit in a version-10-M code."""


def _gf_mul(x: int, y: int) -> int:
    """Multiplication in GF(2^8) modulo x^8 + x^4 + x^3 + x^2 + 1 (0x11D)."""
    z = 0
    for i in range(7, -1, -1):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_divisor(degree: int) -> list[int]:
    """Coefficients of the generator polynomial (x - a^0)...(x - a^(degree-1)), the leading 1
    omitted."""
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _gf_mul(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _gf_mul(root, 0x02)
    return result


def rs_remainder(data: bytes, degree: int) -> bytes:
    """Reed-Solomon error correction codewords of `data`."""
    divisor = _rs_divisor(degree)
    result = [0] * degree
    for byte in data:
        factor = byte ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _gf_mul(coef, factor)
    return bytes(result)


def _data_capacity(version: int) -> int:
    _, groups = _BLOCKS_M[version]
    return sum(blocks * size for blocks, size in groups)


def _count_bits(version: int) -> int:
    return 8 if version < 10 else 16  # noqa: PLR2004 - byte-mode count width per the standard


def choose_version(length: int) -> int:
    for version in range(1, MAX_VERSION + 1):
        if 4 + _count_bits(version) + 8 * length <= 8 * _data_capacity(version):
            return version
    raise QrTooLongError(f"{length} bytes do not fit in a QR code of version {MAX_VERSION}-M")


def encode_data(payload: bytes, version: int) -> bytes:
    """Mode, count, payload, terminator and padding: the data codewords of `version`."""
    bits: list[int] = []

    def put(value: int, width: int) -> None:
        bits.extend((value >> i) & 1 for i in range(width - 1, -1, -1))

    put(_MODE_BYTE, 4)
    put(len(payload), _count_bits(version))
    for byte in payload:
        put(byte, 8)
    capacity = 8 * _data_capacity(version)
    if len(bits) > capacity:
        raise QrTooLongError("payload too long for this version")
    bits.extend([0] * min(4, capacity - len(bits)))
    bits.extend([0] * (-len(bits) % 8))
    data = bytearray(
        sum(bit << (7 - i) for i, bit in enumerate(bits[n : n + 8])) for n in range(0, len(bits), 8)
    )
    pad = 0xEC
    while len(data) < capacity // 8:
        data.append(pad)
        pad ^= 0xEC ^ 0x11
    return bytes(data)


def interleave(data: bytes, version: int) -> bytes:
    """Splits the data codewords into blocks, adds their EC codewords, and interleaves both."""
    ec_len, groups = _BLOCKS_M[version]
    blocks: list[bytes] = []
    start = 0
    for count, size in groups:
        for _ in range(count):
            blocks.append(data[start : start + size])
            start += size
    ecs = [rs_remainder(block, ec_len) for block in blocks]
    out = bytearray()
    for i in range(max(len(b) for b in blocks)):
        out.extend(block[i] for block in blocks if i < len(block))
    for i in range(ec_len):
        out.extend(ec[i] for ec in ecs)
    return bytes(out)


def _mask_bit(mask: int, x: int, y: int) -> bool:  # noqa: PLR0911 - one formula per mask
    if mask == 0:
        return (x + y) % 2 == 0
    if mask == 1:
        return y % 2 == 0
    if mask == 2:  # noqa: PLR2004
        return x % 3 == 0
    if mask == 3:  # noqa: PLR2004
        return (x + y) % 3 == 0
    if mask == 4:  # noqa: PLR2004
        return (x // 3 + y // 2) % 2 == 0
    if mask == 5:  # noqa: PLR2004
        return x * y % 2 + x * y % 3 == 0
    if mask == 6:  # noqa: PLR2004
        return (x * y % 2 + x * y % 3) % 2 == 0
    return ((x + y) % 2 + x * y % 3) % 2 == 0


@dataclass
class _Grid:
    version: int

    def __post_init__(self) -> None:
        self.size = 17 + 4 * self.version
        self.dark = [[False] * self.size for _ in range(self.size)]
        self.function = [[False] * self.size for _ in range(self.size)]

    def set_function(self, x: int, y: int, dark: bool) -> None:
        self.dark[y][x] = dark
        self.function[y][x] = True

    def draw_function_patterns(self) -> None:
        size = self.size
        for i in range(size):
            self.set_function(6, i, i % 2 == 0)
            self.set_function(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < size and 0 <= y < size:
                        self.set_function(x, y, max(abs(dx), abs(dy)) not in (2, 4))
        positions = _ALIGNMENT[self.version]
        last = len(positions) - 1
        for i, cx in enumerate(positions):
            for j, cy in enumerate(positions):
                if (i, j) in ((0, 0), (0, last), (last, 0)):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.set_function(cx + dx, cy + dy, max(abs(dx), abs(dy)) != 1)
        self.draw_format(0)
        self.draw_version()

    def draw_format(self, mask: int) -> None:
        data = _ECL_M << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412
        size = self.size

        def bit(i: int) -> bool:
            return (bits >> i) & 1 == 1

        for i in range(6):
            self.set_function(8, i, bit(i))
        self.set_function(8, 7, bit(6))
        self.set_function(8, 8, bit(7))
        self.set_function(7, 8, bit(8))
        for i in range(9, 15):
            self.set_function(14 - i, 8, bit(i))
        for i in range(8):
            self.set_function(size - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self.set_function(8, size - 15 + i, bit(i))
        self.set_function(8, size - 8, True)

    def draw_version(self) -> None:
        if self.version < 7:  # noqa: PLR2004 - version information exists from version 7
            return
        rem = self.version
        for _ in range(12):
            rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
        bits = self.version << 12 | rem
        for i in range(18):
            dark = (bits >> i) & 1 == 1
            a, b = self.size - 11 + i % 3, i // 3
            self.set_function(a, b, dark)
            self.set_function(b, a, dark)

    def draw_codewords(self, codewords: bytes) -> None:
        size = self.size
        total = len(codewords) * 8
        i = 0
        right = size - 1
        while right >= 1:
            if right == 6:  # noqa: PLR2004 - the vertical timing column is skipped
                right = 5
            upward = (right + 1) & 2 == 0
            for vert in range(size):
                y = size - 1 - vert if upward else vert
                for x in (right, right - 1):
                    if not self.function[y][x] and i < total:
                        self.dark[y][x] = (codewords[i >> 3] >> (7 - (i & 7))) & 1 == 1
                        i += 1
            right -= 2

    def apply_mask(self, mask: int) -> None:
        for y in range(self.size):
            for x in range(self.size):
                if not self.function[y][x] and _mask_bit(mask, x, y):
                    self.dark[y][x] = not self.dark[y][x]


def penalty(dark: list[list[bool]]) -> int:
    """Penalty score of a masked symbol (ISO/IEC 18004 7.8.3): runs, 2x2 blocks, finder-like
    patterns and dark-module balance."""
    size = len(dark)
    score = 0
    lines = [*dark, *([dark[y][x] for y in range(size)] for x in range(size))]
    finder_a = [True, False, True, True, True, False, True, False, False, False, False]
    finder_b = finder_a[::-1]
    for line in lines:
        run = 1
        for i in range(1, size + 1):
            if i < size and line[i] == line[i - 1]:
                run += 1
                continue
            if run >= 5:  # noqa: PLR2004
                score += 3 + run - 5
            run = 1
        for i in range(size - 10):
            window = line[i : i + 11]
            if window in (finder_a, finder_b):
                score += 40
    for y in range(size - 1):
        for x in range(size - 1):
            color = dark[y][x]
            if color == dark[y][x + 1] == dark[y + 1][x] == dark[y + 1][x + 1]:
                score += 3
    dark_count = sum(sum(row) for row in dark)
    total = size * size
    score += 10 * (abs(dark_count * 20 - total * 10) // total)
    return score


def encode(text: str, *, mask: int | None = None) -> list[list[bool]]:
    """The modules of a QR code for `text` (UTF-8, byte mode, level M), `True` for dark.
    `mask` forces a mask pattern (tests); by default the one with the lowest penalty."""
    payload = text.encode("utf-8")
    version = choose_version(len(payload))
    codewords = interleave(encode_data(payload, version), version)

    def masked(candidate: int) -> list[list[bool]]:
        grid = _Grid(version)
        grid.draw_function_patterns()
        grid.draw_codewords(codewords)
        grid.apply_mask(candidate)
        grid.draw_format(candidate)
        return grid.dark

    if mask is not None:
        return masked(mask)
    # The first mask wins ties, as in the standard's reference order.
    return min((masked(candidate) for candidate in range(8)), key=penalty)


def to_svg(modules: list[list[bool]], *, label: str) -> Markup:
    """Inline SVG (one path, quiet zone included) that scales with CSS. Built only from the
    module bits and a translated label, which is escaped."""
    size = len(modules) + 2 * QUIET_ZONE
    path = "".join(
        f"M{x + QUIET_ZONE} {y + QUIET_ZONE}h1v1h-1z"
        for y, row in enumerate(modules)
        for x, dark in enumerate(row)
        if dark
    )
    return Markup(
        '<svg xmlns="http://www.w3.org/2000/svg" class="qr" role="img" '
        'viewBox="0 0 {size} {size}" shape-rendering="crispEdges" aria-label="{label}">'
        '<rect width="{size}" height="{size}" fill="#fff"/>'
        '<path fill="#000" d="{path}"/></svg>'
    ).format(size=size, label=label, path=path)
