# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Lyrics test helpers: library tracks inserted with plain SQL, LRCLIB fixture bodies."""

from pathlib import Path

from ultimatetunes.core.clock import FakeClock, format_ts
from ultimatetunes.db import Database

FIXTURES = Path(__file__).parent / "fixtures"
TRACK_ID = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01b001"
OTHER_ID = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01b002"
MERGED_ID = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01b003"
VIDEO_ID = "Qx7Lm2pZ0aB"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def add_track(  # noqa: PLR0913 - test helper mirroring the columns it fills
    db: Database,
    clock: FakeClock,
    track_id: str = TRACK_ID,
    *,
    title: str = "Lighthouse Keeper",
    artist: str = "The Paper Lanterns",
    album: str | None = "Harbour Lights",
    duration_ms: int | None = 212_400,
    status: str = "ready",
    merged_into: str | None = None,
    alias: str | None = None,
) -> str:
    now = format_ts(clock.now())
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO tracks (id, status, title, title_norm, artist_name, album_name,"
            " duration_ms, merged_into, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                track_id,
                status,
                title,
                title.lower(),
                artist,
                album,
                duration_ms,
                merged_into,
                now,
                now,
            ),
        )
        if alias is not None:
            conn.execute(
                "INSERT INTO track_aliases (alias, track_id, created_at) VALUES (?, ?, ?)",
                (alias, track_id, now),
            )
    return track_id
