# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""A small invented library next to `FakeMusicCatalog`, for search tests.

- The Paper Lanterns (`UCq8…`, the fake catalog's artist): albums Harbour Lights (two ready
  songs) and Lanterns at Dusk (`MPREb_k3Vd9QmT2xL`, one ready song archived from
  `yt:Fk2Lp9QwXa1`). `yt:Wq5Jd7HsKe2` ("Night Ferry" in the catalog) is also an alias of
  Lighthouse Keeper, so it shows as that library song.
- `yt:Rb8Tn3ZcYv0` ("Glass Orchard") was requested: pending.
- Neon Harbor (`UCn4…`) and its album Static Bloom (`MPREb_Hn2Vq8Lr5Tz`) exist with a pending
  track only, so they are not in the library results yet.
- The user ana starred Lighthouse Keeper, Harbour Lights and The Paper Lanterns.
"""

import pytest

from ultimatetunes.db import Database
from ultimatetunes.db.driver import Connection

NOW = "2026-10-01T10:00:00.000Z"
USER = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01e001"
LANTERNS = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01a001"
HARBOR = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01a002"
HARBOUR_LIGHTS = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01b001"
DUSK = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01b002"
BLOOM = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01b003"
LIGHTHOUSE = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01c001"
TIDEWATER = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01c002"
LOW_TIDE = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01c003"
ORCHARD = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01c004"
SIGNAL = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01c005"


def _artist(conn: Connection, artist_id: str, name: str, channel: str) -> None:
    conn.execute(
        "INSERT INTO artists (id, name, name_norm, sort_name, musicbrainz_id, yt_channel_id,"
        " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (artist_id, name, name.lower(), None, None, channel, NOW, NOW),
    )


def _album(conn: Connection, album_id: str, artist_id: str, name: str, browse: str | None) -> None:
    conn.execute(
        "INSERT INTO albums (id, artist_id, name, name_norm, year, genre, yt_browse_id,"
        " created_at, updated_at) VALUES (?, ?, ?, ?, 2023, 'Indie Pop', ?, ?, ?)",
        (album_id, artist_id, name, name.lower(), browse, NOW, NOW),
    )


def _track(  # noqa: PLR0913 - the columns a test cares about
    conn: Connection,
    track_id: str,
    status: str,
    title: str,
    *,
    artist: tuple[str, str] | None,
    album: tuple[str, str] | None,
    number: int | None,
    video: str | None,
) -> None:
    ready = status == "ready"
    conn.execute(
        "INSERT INTO tracks (id, status, title, title_norm, artist_id, album_id, artist_name,"
        " album_name, track_number, disc_number, year, duration_ms, path, format, content_type,"
        " size_bytes, bit_rate_kbps, sample_rate_hz, channels, rg_track_gain_db, rg_track_peak,"
        " yt_video_id, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            track_id,
            status,
            title,
            title.lower(),
            artist[0] if artist else None,
            album[0] if album else None,
            artist[1] if artist else "Unknown",
            album[1] if album else None,
            number,
            1 if ready else None,
            2023 if ready else None,
            214_400 if ready else None,
            f"The Paper Lanterns/{title}.opus" if ready else None,
            "opus" if ready else None,
            "audio/ogg" if ready else None,
            3489211 if ready else None,
            128 if ready else None,
            48000 if ready else None,
            2 if ready else None,
            -7.12 if ready else None,
            0.988 if ready else None,
            video,
            NOW,
            NOW,
        ),
    )
    if video:
        _alias(conn, video, track_id)


def _alias(conn: Connection, video: str, track_id: str) -> None:
    conn.execute(
        "INSERT INTO track_aliases (alias, track_id, created_at) VALUES (?, ?, ?)",
        (f"yt:{video}", track_id, NOW),
    )


def seed_library(db: Database) -> None:
    lanterns = (LANTERNS, "The Paper Lanterns")
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO users (id, username, password_hash, role, created_at, updated_at)"
            " VALUES (?, 'ana', 'x', 'admin', ?, ?)",
            (USER, NOW, NOW),
        )
        _artist(conn, LANTERNS, "The Paper Lanterns", "UCq8XbV1r0LwZ5mN3tYp7kQe")
        _artist(conn, HARBOR, "Neon Harbor", "UCn4HbR7oQ2sLx9TzV0eWm3K")
        _album(conn, HARBOUR_LIGHTS, LANTERNS, "Harbour Lights", None)
        _album(conn, DUSK, LANTERNS, "Lanterns at Dusk", "MPREb_k3Vd9QmT2xL")
        _album(conn, BLOOM, HARBOR, "Static Bloom", "MPREb_Hn2Vq8Lr5Tz")
        lights = (HARBOUR_LIGHTS, "Harbour Lights")
        _track(
            conn,
            LIGHTHOUSE,
            "ready",
            "Lighthouse Keeper",
            artist=lanterns,
            album=lights,
            number=1,
            video=None,
        )
        _alias(conn, "Wq5Jd7HsKe2", LIGHTHOUSE)
        _track(
            conn,
            TIDEWATER,
            "ready",
            "Tidewater",
            artist=lanterns,
            album=lights,
            number=2,
            video=None,
        )
        dusk = (DUSK, "Lanterns at Dusk")
        _track(
            conn,
            LOW_TIDE,
            "ready",
            "Low Tide Letters",
            artist=lanterns,
            album=dusk,
            number=1,
            video="Fk2Lp9QwXa1",
        )
        _track(
            conn,
            ORCHARD,
            "pending",
            "Glass Orchard",
            artist=None,
            album=None,
            number=None,
            video="Rb8Tn3ZcYv0",
        )
        bloom = (BLOOM, "Static Bloom")
        harbor = (HARBOR, "Neon Harbor")
        _track(
            conn,
            SIGNAL,
            "pending",
            "Signal Fires",
            artist=harbor,
            album=bloom,
            number=2,
            video="Tz9Kd4Wb7Rc",
        )
        conn.execute(
            "INSERT INTO starred_tracks (user_id, track_id, starred_at) VALUES (?, ?, ?)",
            (USER, LIGHTHOUSE, NOW),
        )
        conn.execute(
            "INSERT INTO starred_albums (user_id, album_id, starred_at) VALUES (?, ?, ?)",
            (USER, HARBOUR_LIGHTS, NOW),
        )
        conn.execute(
            "INSERT INTO starred_artists (user_id, artist_id, starred_at) VALUES (?, ?, ?)",
            (USER, LANTERNS, NOW),
        )
        conn.execute(
            "INSERT INTO user_track_stats (user_id, track_id, play_count, last_played_at)"
            " VALUES (?, ?, 14, ?)",
            (USER, LIGHTHOUSE, NOW),
        )


@pytest.fixture
def library(db: Database) -> Database:
    seed_library(db)
    return db
