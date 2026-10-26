#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Render the web player's PNG icons from static/web/icon.svg (needs ImageMagick with librsvg).

iOS ignores SVG for the home screen and fills transparency with black, so the touch icon is the
tile edge to edge (iOS rounds it itself). The maskable icon is the same with the note inside the
80 % safe zone. Run from the repo root; commit the PNGs.
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "server/src/ultimatetunes/static/web"
SOURCE = STATIC / "icon.svg"
SQUARE = '<rect x="18" y="18" width="72" height="72"'
SAFE = "translate(54 54) scale(0.8) translate(-54 -54) "  # about the middle of the 18..90 tile

# name -> (size, full-bleed square, note scaled into the safe zone)
ICONS = {
    "apple-touch-icon.png": (180, True, False),
    "icon-192.png": (192, False, False),
    "icon-512.png": (512, False, False),
    "icon-maskable-512.png": (512, True, True),
}


def variant(svg: str, square: bool, safe: bool) -> str:
    if square:
        svg = re.sub(r'<use href="#shape"', SQUARE, svg)
    if safe:
        svg = svg.replace('<path transform="', f'<path transform="{SAFE}', 1)
    return svg


def main() -> int:
    source = SOURCE.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        for name, (size, square, safe) in ICONS.items():
            svg = Path(tmp) / "icon.svg"
            svg.write_text(variant(source, square, safe), encoding="utf-8")
            subprocess.run(
                ["magick", "-background", "none", "-density", str(int(96 * size / 72) + 1),
                 str(svg), "-resize", f"{size}x{size}", *(["-alpha", "off"] if square else []),
                 "-depth", "8", "-strip",
                 "-define", "png:compression-level=9", "-define", "png:exclude-chunks=all",
                 str(STATIC / name)],
                check=True,
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
