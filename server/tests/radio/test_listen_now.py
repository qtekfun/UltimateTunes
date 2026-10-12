# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Listen Now shelves on the search tests' library, plus plays and stars of ana."""

from typing import Any, cast

import pytest

from tests.search.conftest import (
    DUSK,
    HARBOUR_LIGHTS,
    LIGHTHOUSE,
    LOW_TIDE,
    NOW,
    ORCHARD,
    TIDEWATER,
    USER,
)
from tests.search.test_routes import schema_validator
from ultimatetunes.db import Database
from ultimatetunes.db.driver import Connection
from ultimatetunes.radio.listen_now import MAX_ALBUMS, listen_now

LISTEN_NOW = schema_validator("ut-v1.yaml", "ListenNow")
OTHER = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01e002"
LOST = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01c020"
MERGED = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01c021"


def shelf(db: Database, user: str) -> dict[str, Any]:
    return cast("dict[str, Any]", listen_now(db, user))


def ts(minute: int) -> str:
    return f"2026-10-02T10:{minute:02d}:00.000Z"


def play(conn: Connection, user: str, track: str, minute: int, *, submission: int = 1) -> None:
    conn.execute(
        "INSERT INTO play_history (id, user_id, track_id, played_at, submission)"
        " VALUES (?, ?, ?, ?, ?)",
        (
            f"0199d6a2-4c1e-7b3a-9f10-{user[-3:]}{track[-3:]}{minute:06d}",
            user,
            track,
            ts(minute),
            submission,
        ),
    )


def stats(conn: Connection, user: str, track: str, count: int, minute: int) -> None:
    conn.execute(
        "INSERT INTO user_track_stats (user_id, track_id, play_count, last_played_at)"
        " VALUES (?, ?, ?, ?)",
        (user, track, count, ts(minute)),
    )


@pytest.fixture
def shelves(library: Database) -> Database:
    with library.transaction() as conn:
        conn.execute(
            "INSERT INTO users (id, username, password_hash, role, created_at, updated_at)"
            " VALUES (?, 'ben', 'x', 'user', ?, ?)",
            (OTHER, NOW, NOW),
        )
        # A failed track without a video, and a merged one: neither can be listed.
        conn.execute(
            "INSERT INTO tracks (id, status, title, title_norm, artist_name, created_at,"
            " updated_at) VALUES (?, 'failed', 'Lost', 'lost', 'Nobody', ?, ?)",
            (LOST, NOW, NOW),
        )
        conn.execute(
            "INSERT INTO tracks (id, status, title, title_norm, artist_name, merged_into,"
            " created_at, updated_at) VALUES (?, 'merged', 'Old', 'old', 'X', ?, ?, ?)",
            (MERGED, LOW_TIDE, NOW, NOW),
        )
        play(conn, USER, TIDEWATER, 1)
        play(conn, USER, LOW_TIDE, 2)
        play(conn, USER, LIGHTHOUSE, 3)
        # "Now playing" notifications and other users' plays do not count.
        play(conn, USER, LOW_TIDE, 9, submission=0)
        play(conn, OTHER, LOW_TIDE, 8)
        play(conn, USER, ORCHARD, 7)
        stats(conn, USER, ORCHARD, 5, 7)
        stats(conn, USER, TIDEWATER, 5, 1)
        stats(conn, USER, LOST, 9, 1)
        stats(conn, USER, MERGED, 30, 1)
        stats(conn, USER, LOW_TIDE, 0, 1)
        stats(conn, OTHER, LOW_TIDE, 50, 8)
        conn.execute(
            "INSERT INTO starred_tracks (user_id, track_id, starred_at) VALUES (?, ?, ?)",
            (USER, ORCHARD, ts(5)),
        )
        conn.execute(
            "INSERT INTO starred_tracks (user_id, track_id, starred_at) VALUES (?, ?, ?)",
            (USER, LOST, ts(6)),
        )
    return library


def test_shelves(shelves: Database) -> None:
    body = shelf(shelves, USER)
    LISTEN_NOW.validate(body)
    assert [a["id"] for a in body["recentlyPlayed"]] == [HARBOUR_LIGHTS, DUSK]
    assert [a["id"] for a in body["recentlyAdded"]] == [DUSK, HARBOUR_LIGHTS]
    assert body["recentlyAdded"][0]["coverArt"] == f"al-{DUSK}"
    most = body["mostPlayed"]
    # Ties broken by the latest play; the pending song keeps its yt: id.
    assert [(s["id"], s["libraryState"]) for s in most] == [
        (LIGHTHOUSE, "ready"),
        ("yt:Rb8Tn3ZcYv0", "pending"),
        (TIDEWATER, "ready"),
    ]
    assert most[1]["isExternal"] is True
    assert most[1]["coverArt"] == "yt:Rb8Tn3ZcYv0"
    assert body["favouriteRadios"] == [
        {
            "seedId": "yt:Rb8Tn3ZcYv0",
            "title": "Glass Orchard Radio",
            "subtitle": "Unknown",
            "coverArt": "yt:Rb8Tn3ZcYv0",
        },
        {
            "seedId": LIGHTHOUSE,
            "title": "Lighthouse Keeper Radio",
            "subtitle": "The Paper Lanterns",
            "coverArt": f"al-{HARBOUR_LIGHTS}",
        },
    ]


def test_pending_song_with_youtube_album_and_artist(shelves: Database) -> None:
    body = shelf(shelves, USER)
    with shelves.transaction() as conn:
        conn.execute(
            "UPDATE tracks SET album_name = 'Lanterns at Dusk', yt_album_browse_id = ?,"
            " yt_artist_channel_id = ?, duration_ms = 198400 WHERE id = ?",
            ("MPREb_k3Vd9QmT2xL", "UCq8XbV1r0LwZ5mN3tYp7kQe", ORCHARD),
        )
    item = shelf(shelves, USER)["mostPlayed"][1]
    assert body["mostPlayed"][1]["albumId"] is None
    assert item["albumId"] == "ytalbum:MPREb_k3Vd9QmT2xL"
    assert item["artistId"] == "ytartist:UCq8XbV1r0LwZ5mN3tYp7kQe"
    assert item["album"] == "Lanterns at Dusk"
    assert item["durationSec"] == 198


def test_malformed_youtube_ids_are_dropped(shelves: Database) -> None:
    with shelves.transaction() as conn:
        conn.execute(
            "UPDATE tracks SET album_name = 'X', yt_album_browse_id = 'bad id',"
            " yt_artist_channel_id = 'bad id' WHERE id = ?",
            (ORCHARD,),
        )
    item = shelf(shelves, USER)["mostPlayed"][1]
    assert item["id"] == "yt:Rb8Tn3ZcYv0"
    assert item["albumId"] is None
    assert item["artistId"] is None


def test_another_user_has_only_the_shared_shelf(shelves: Database) -> None:
    body = shelf(shelves, OTHER)
    LISTEN_NOW.validate(body)
    assert [a["id"] for a in body["recentlyPlayed"]] == [DUSK]
    assert [a["id"] for a in body["recentlyAdded"]] == [DUSK, HARBOUR_LIGHTS]
    assert [s["id"] for s in body["mostPlayed"]] == [LOW_TIDE]
    assert body["favouriteRadios"] == []


def test_empty_library(db: Database) -> None:
    body = shelf(db, USER)
    LISTEN_NOW.validate(body)
    assert body == {
        "recentlyPlayed": [],
        "recentlyAdded": [],
        "mostPlayed": [],
        "favouriteRadios": [],
    }
    assert MAX_ALBUMS == 20
