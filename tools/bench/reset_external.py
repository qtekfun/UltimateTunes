# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Forgets every track that came from the (fake) catalog, so it is external again (PLAN T21).

Bench stack only, never a real server: the fake catalog has seven songs, and an external
first-sound sample needs a song that was never played. Run inside the api container:
    docker exec -i ut-bench-api-1 python - < tools/bench/reset_external.py
Deletes the archived files of tracks with a YouTube video id (under /music only), then the
rows (jobs and aliases go with them, ON DELETE CASCADE), and the search cache.
"""

import sqlite3
from pathlib import Path

MUSIC = Path("/music").resolve()
DB = Path("/data/ultimatetunes.db")

conn = sqlite3.connect(DB)
conn.execute("PRAGMA foreign_keys = ON")
rows = conn.execute("SELECT id, path FROM tracks WHERE yt_video_id IS NOT NULL").fetchall()
for _, rel in rows:
    if rel:
        path = (MUSIC / rel).resolve()
        if path.is_relative_to(MUSIC) and path.is_file():
            path.unlink()
with conn:
    conn.execute("DELETE FROM tracks WHERE yt_video_id IS NOT NULL")
    conn.execute("DELETE FROM cache_entries")
conn.close()
print(f"forgot {len(rows)} external track(s)")
