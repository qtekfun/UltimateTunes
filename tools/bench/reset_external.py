# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Forgets every track that came from the (fake) catalog, so it is external again (PLAN T21).

Bench stack only, never a real server: the fake catalog has seven songs, and an external
first-sound sample needs a song that was never played. From the host:
    python3 tools/bench/reset_external.py [PROJECT]      (default project: ut-bench)
It sends itself to `<PROJECT>-api-1` (`docker exec -i … python - --inside`), which deletes the
archived files of tracks with a YouTube video id (under /music only), then the rows (jobs and
aliases go with them, ON DELETE CASCADE), and the search cache.
"""

import sqlite3
import subprocess
import sys
from pathlib import Path

MUSIC = Path("/music")
DB = Path("/data/ultimatetunes.db")


def inside() -> int:
    music = MUSIC.resolve()
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA foreign_keys = ON")
    rows = conn.execute("SELECT id, path FROM tracks WHERE yt_video_id IS NOT NULL").fetchall()
    for _, rel in rows:
        if rel:
            path = (music / rel).resolve()
            if path.is_relative_to(music) and path.is_file():
                path.unlink()
    with conn:
        conn.execute("DELETE FROM tracks WHERE yt_video_id IS NOT NULL")
        conn.execute("DELETE FROM cache_entries")
    conn.close()
    print(f"forgot {len(rows)} external track(s)")
    return 0


def from_host(project: str) -> int:
    source = Path(__file__).read_bytes()
    command = ["docker", "exec", "-i", f"{project}-api-1", "python", "-", "--inside"]
    return subprocess.run(command, input=source, check=False).returncode  # noqa: S603


if __name__ == "__main__":
    if sys.argv[1:] == ["--inside"]:
        sys.exit(inside())
    sys.exit(from_host(sys.argv[1] if len(sys.argv) > 1 else "ut-bench"))
