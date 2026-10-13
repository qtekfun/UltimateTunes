# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Commands of the library area (`commands.AREAS`). Owner: PLAN T05.

`ultimatetunes scan-library [--full]` registers the audio files of `/music` (`library.scan`):
new and changed files by default, every file with `--full`. A file is "changed" when its size
changed: after editing tags in place without changing the size, run it with `--full`. Run
`ultimatetunes migrate` first.

`ultimatetunes refetch-failed [--truncated] [--dry-run]` requeues downloads that were cut off
(`library.refetch`): every `failed` download, and with `--truncated` also archived songs whose
file on disk is shorter than recorded. `--dry-run` only counts them. Run it where the database
and `/music` are (the api role), never the worker.
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


def run_refetch(settings: Settings, args: Sequence[str], out: TextIO | None = None) -> int:
    from ultimatetunes.core.clock import SystemClock  # noqa: PLC0415
    from ultimatetunes.core.storage import LocalLibraryStore  # noqa: PLC0415
    from ultimatetunes.db.database import Database  # noqa: PLC0415
    from ultimatetunes.jobs.queue import SqliteJobQueue  # noqa: PLC0415
    from ultimatetunes.library.refetch import Refetcher  # noqa: PLC0415

    out = out or sys.stdout
    allowed = {"--truncated", "--dry-run"}
    if any(a not in allowed for a in args) or len(set(args)) != len(args):
        out.write("usage: ultimatetunes refetch-failed [--truncated] [--dry-run]\n")
        return 2
    truncated = "--truncated" in args
    dry_run = "--dry-run" in args
    clock = SystemClock()
    db = Database.sqlite(settings.database_file, readers=1)
    try:
        refetcher = Refetcher(
            db, SqliteJobQueue(db, clock), LocalLibraryStore(settings.music_dir), clock
        )
        result = refetcher.refetch(truncated=truncated, dry_run=dry_run)
    finally:
        db.close()
    verb = "would requeue" if dry_run else "requeued"
    tail = f", {result.truncated} truncated" if truncated else ""
    out.write(f"{verb} {result.failed} failed{tail} download(s)\n")
    return 0


def register(registry: CommandRegistry) -> None:
    registry.add("scan-library", run_scan, help="Register the audio files of /music")
    registry.add(
        "refetch-failed",
        run_refetch,
        help="Requeue failed (and with --truncated, short) downloads",
    )
