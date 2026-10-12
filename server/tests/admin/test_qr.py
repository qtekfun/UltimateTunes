# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The QR encoder against reference matrices from an independent implementation, plus the
Reed-Solomon vector of the standard's worked example."""

from pathlib import Path

import pytest

from ultimatetunes.admin import qr

REFERENCE = Path(__file__).with_name("qr_reference.txt")


def _cases() -> list[tuple[int, str, list[str]]]:
    cases: list[tuple[int, str, list[str]]] = []
    for line in REFERENCE.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            continue
        if line.startswith("case "):
            _, mask, text = line.split(" ", 2)
            cases.append((int(mask), text, []))
        else:
            cases[-1][2].append(line)
    return cases


@pytest.mark.parametrize(("mask", "text", "rows"), _cases())
def test_matches_reference(mask: int, text: str, rows: list[str]) -> None:
    modules = qr.encode(text, mask=mask)
    assert ["".join("1" if dark else "0" for dark in row) for row in modules] == rows


def test_reed_solomon_example() -> None:
    # ISO/IEC 18004 annex I: "01234567" in 1-M; data codewords and their 10 EC codewords.
    data = bytes([16, 32, 12, 86, 97, 128, 236, 17, 236, 17, 236, 17, 236, 17, 236, 17])
    assert list(qr.rs_remainder(data, 10)) == [165, 36, 212, 193, 237, 54, 199, 135, 44, 85]


def test_versions_and_limits() -> None:
    assert qr.choose_version(14) == 1
    assert qr.choose_version(15) == 2
    assert qr.choose_version(213) == 10
    with pytest.raises(qr.QrTooLongError):
        qr.choose_version(214)
    with pytest.raises(qr.QrTooLongError):
        qr.encode("x" * 214)
    with pytest.raises(qr.QrTooLongError):
        qr.encode_data(b"x" * 20, 1)


def test_automatic_mask_has_the_lowest_penalty() -> None:
    text = "ultimatetunes://connect?url=https%3A%2F%2Fm.example.net&key=utk_x"
    chosen = qr.penalty(qr.encode(text))
    assert all(chosen <= qr.penalty(qr.encode(text, mask=m)) for m in range(8))


def test_svg_is_inline_and_escaped() -> None:
    svg = str(qr.to_svg(qr.encode("HELLO"), label='a "quoted" <label>'))
    assert svg.startswith('<svg xmlns="http://www.w3.org/2000/svg"')
    assert 'viewBox="0 0 29 29"' in svg
    assert "&#34;quoted&#34; &lt;label&gt;" in svg
    assert "M4 4h1v1h-1z" in svg  # the top-left finder starts at the quiet zone
