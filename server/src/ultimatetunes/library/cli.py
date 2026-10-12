# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Commands of the library area (`commands.AREAS`). Owner: PLAN T05.

`ultimatetunes scan-library [--full]` registers the audio files of `/music` (`library.scan`):
new and changed files by default, every file with `--full`. Run `ultimatetunes migrate` first.
"""

import sys
from collections.abc import Sequence
from typing import TextIO

from ultimatetunes.commands import CommandRegistry
from ultimatetunes.settings import Settings


def run_scan(settings: Settings, args: Sequence[str], out: TextIO | None = None) -> int:
    # Heavy imports inside the command (commands.py).
    from ultimatetunes.core.clock import SystemClock  # noqa: PLC0415
    from ultimatetunes.core.storage import LocalLibraryStore  # noqa: PLC0415
    from ultimatetunes.db.database import Database  # noqa: PLC0415
    from ultimatetunes.library.scan import LibraryScanner  # noqa: PLC0415

    out = out or sys.stdout
    if any(a != "--full" for a in args):
        out.write("usage: ultimatetunes scan-library [--full]\n")
        return 2
    db = Database.sqlite(settings.database_file, readers=1)
    try:
        scanner = LibraryScanner(db, LocalLibraryStore(settings.music_dir), SystemClock())
        result = scanner.scan(full="--full" in args)
    finally:
        db.close()
    out.write(
        f"added {result.added}, updated {result.updated}, unchanged {result.unchanged},"
        f" skipped {result.skipped}, failed {result.failed}, missing {result.missing}\n"
    )
    return 1 if result.failed else 0


def register(registry: CommandRegistry) -> None:
    registry.add("scan-library", run_scan, help="Register the audio files of /music")
