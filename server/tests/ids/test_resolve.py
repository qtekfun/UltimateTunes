# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Virtual ↔ library resolution and materialization (contracts/ids.md, "Resolution rules")."""

import pytest

from ultimatetunes.core.clock import FakeClock, format_ts
from ultimatetunes.db import Database
from ultimatetunes.db.driver import Connection
from ultimatetunes.errors import InvalidId, NotFound
from ultimatetunes.ids import VirtualId
from ultimatetunes.ids.resolve import (
    TrackRef,
    albums_for_browse_ids,
    artists_for_channel_ids,
    materialize_song,
    resolve_track,
    tracks_for_videos,
)
from ultimatetunes.search.catalog import AlbumRef, ArtistRef, CatalogTrack, Thumbnail

NOW = "2026-10-12T08:00:00.000Z"
READY = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01c001"
PENDING = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01c002"
MERGED = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01c003"
ORPHAN = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01c004"
BY_COLUMN = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01c005"
CHAINED = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01c006"
MISSING = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01c0ff"
ARTIST = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01a001"
ALBUM = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01b001"


def add_track(
    conn: Connection,
    track_id: str,
    status: str,
    *,
    video: str | None = None,
    merged_into: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO tracks (id, status, title, title_norm, artist_name, yt_video_id,"
        " merged_into, created_at, updated_at) VALUES (?, ?, 'Song', 'song', 'Band', ?, ?, ?, ?)",
        (track_id, status, video, merged_into, NOW, NOW),
    )


def alias(conn: Connection, video: str, track_id: str) -> None:
    conn.execute(
        "INSERT INTO track_aliases (alias, track_id, created_at) VALUES (?, ?, ?)",
        (f"yt:{video}", track_id, NOW),
    )


@pytest.fixture
def library(db: Database) -> Database:
    with db.transaction() as conn:
        add_track(conn, READY, "ready", video="ReadyVideo1")
        alias(conn, "ReadyVideo1", READY)
        alias(conn, "ReadyOmv001", READY)
        add_track(conn, PENDING, "pending", video="PendingVid1")
        alias(conn, "PendingVid1", PENDING)
        add_track(conn, MERGED, "merged", video="MergedVid01", merged_into=READY)
        alias(conn, "MergedVid01", MERGED)
        add_track(conn, CHAINED, "merged", merged_into=MERGED)
        alias(conn, "ChainedVid1", CHAINED)
        add_track(conn, ORPHAN, "merged", video="OrphanVid01")
        alias(conn, "OrphanVid01", ORPHAN)
        add_track(conn, BY_COLUMN, "failed", video="ColumnVid01")
        conn.execute(
            "INSERT INTO artists (id, name, name_norm, yt_channel_id, created_at, updated_at)"
            " VALUES (?, 'Band', 'band', 'UCband', ?, ?)",
            (ARTIST, NOW, NOW),
        )
        conn.execute(
            "INSERT INTO albums (id, artist_id, name, name_norm, yt_browse_id, created_at,"
            " updated_at) VALUES (?, ?, 'Record', 'record', 'MPREb_record', ?, ?)",
            (ALBUM, ARTIST, NOW, NOW),
        )
    return db


def test_library_uuid(library: Database) -> None:
    with library.read() as conn:
        assert resolve_track(conn, READY) == TrackRef(READY, "ready")
        assert resolve_track(conn, PENDING.upper()) == TrackRef(PENDING, "pending")
        assert resolve_track(conn, BY_COLUMN) == TrackRef(BY_COLUMN, "failed")


def test_merged_uuid_resolves_one_hop(library: Database) -> None:
    with library.read() as conn:
        assert resolve_track(conn, MERGED) == TrackRef(READY, "ready")


@pytest.mark.parametrize("track_id", [MISSING, ORPHAN, CHAINED])
def test_unknown_or_dangling_uuid_is_not_found(library: Database, track_id: str) -> None:
    with library.read() as conn, pytest.raises(NotFound):
        resolve_track(conn, track_id)


def test_yt_ids(library: Database) -> None:
    with library.read() as conn:
        assert resolve_track(conn, "yt:ReadyVideo1") == TrackRef(READY, "ready")
        assert resolve_track(conn, "yt:ReadyOmv001") == TrackRef(READY, "ready")
        assert resolve_track(conn, "yt:PendingVid1") == TrackRef(PENDING, "pending")
        assert resolve_track(conn, "yt:MergedVid01") == TrackRef(READY, "ready")
        # No alias, but the track carries the video id.
        assert resolve_track(conn, "yt:ColumnVid01") == TrackRef(BY_COLUMN, "failed")
        assert resolve_track(conn, "yt:Unknown0001") == VirtualId("song", "Unknown0001")
        # An alias to a merged track whose target is gone is treated as unknown.
        assert resolve_track(conn, "yt:OrphanVid01") == VirtualId("song", "OrphanVid01")


@pytest.mark.parametrize("raw", ["ytalbum:MPREb_record", "ytartist:UCband", "yt:bad", "x"])
def test_invalid_song_ids(library: Database, raw: str) -> None:
    with library.read() as conn, pytest.raises(InvalidId):
        resolve_track(conn, raw)


def test_bulk_lookup(library: Database) -> None:
    videos = ["ReadyVideo1", "PendingVid1", "ColumnVid01", "Unknown0001", "ReadyVideo1"]
    with library.read() as conn:
        assert tracks_for_videos(conn, videos) == {
            "ReadyVideo1": TrackRef(READY, "ready"),
            "PendingVid1": TrackRef(PENDING, "pending"),
            "ColumnVid01": TrackRef(BY_COLUMN, "failed"),
        }
        # All found through aliases: no second query.
        assert tracks_for_videos(conn, ["ReadyOmv001"]) == {"ReadyOmv001": TrackRef(READY, "ready")}
        assert tracks_for_videos(conn, []) == {}


def test_bulk_lookup_in_chunks(library: Database) -> None:
    many = [f"Filler{i:05d}" for i in range(1200)] + ["PendingVid1", "ColumnVid01"]
    with library.read() as conn:
        found = tracks_for_videos(conn, many)
    assert set(found) == {"PendingVid1", "ColumnVid01"}


def test_dangling_track_by_column_is_skipped(db: Database) -> None:
    with db.transaction() as conn:
        add_track(conn, ORPHAN, "merged", video="OrphanVid01")
    with db.read() as conn:
        assert tracks_for_videos(conn, ["OrphanVid01"]) == {}


def test_albums_and_artists_by_youtube_id(library: Database) -> None:
    with library.read() as conn:
        assert albums_for_browse_ids(conn, ["MPREb_record", "MPREb_other"]) == {
            "MPREb_record": ALBUM
        }
        assert artists_for_channel_ids(conn, ["UCband", "UCother"]) == {"UCband": ARTIST}
        assert albums_for_browse_ids(conn, []) == {}


SONG = CatalogTrack(
    video_id="NewVideo001",
    title="Glass Orchard",
    artists=(ArtistRef("The Paper Lanterns", "UCq8XbV1r0LwZ5mN3tYp7kQe"), ArtistRef("Guest")),
    album=AlbumRef("Lanterns at Dusk", "MPREb_k3Vd9QmT2xL"),
    duration_s=198,
    year=2024,
    track_number=2,
    thumbnail=Thumbnail("https://i.ytimg.com/vi/NewVideo001/hqdefault.jpg", 480, 360),
)


def test_materialize_creates_a_pending_track_once(library: Database, clock: FakeClock) -> None:
    with library.transaction() as conn:
        ref = materialize_song(conn, clock, SONG)
    assert ref.status == "pending"
    with library.transaction() as conn:
        assert materialize_song(conn, clock, SONG) == ref
    with library.read() as conn:
        row = conn.execute("SELECT * FROM tracks WHERE id = ?", (ref.id,)).fetchone()
        aliases = conn.execute(
            "SELECT alias FROM track_aliases WHERE track_id = ?", (ref.id,)
        ).fetchall()
    assert row is not None
    assert row["title"] == "Glass Orchard"
    assert row["title_norm"] == "glass orchard"
    assert row["artist_name"] == "The Paper Lanterns, Guest"
    assert row["album_name"] == "Lanterns at Dusk"
    assert row["duration_ms"] == 198000
    assert row["yt_album_browse_id"] == "MPREb_k3Vd9QmT2xL"
    assert row["yt_artist_channel_id"] == "UCq8XbV1r0LwZ5mN3tYp7kQe"
    assert row["yt_thumbnail_url"] == "https://i.ytimg.com/vi/NewVideo001/hqdefault.jpg"
    assert row["created_at"] == format_ts(clock.now())
    assert aliases == [{"alias": "yt:NewVideo001"}]


def test_materialize_minimal_track(library: Database, clock: FakeClock) -> None:
    bare = CatalogTrack("BareVideo01", "Untitled", ())
    with library.transaction() as conn:
        ref = materialize_song(conn, clock, bare)
        row = conn.execute("SELECT * FROM tracks WHERE id = ?", (ref.id,)).fetchone()
    assert row is not None
    assert (row["artist_name"], row["album_name"], row["duration_ms"]) == ("", None, None)
    assert row["yt_artist_channel_id"] is None
    assert row["yt_thumbnail_url"] is None


def test_materialize_reuses_known_tracks(library: Database, clock: FakeClock) -> None:
    with library.transaction() as conn:
        assert materialize_song(conn, clock, CatalogTrack("ReadyVideo1", "x", ())) == TrackRef(
            READY, "ready"
        )
        # Known by its column only: the missing alias is added.
        assert materialize_song(conn, clock, CatalogTrack("ColumnVid01", "x", ())) == TrackRef(
            BY_COLUMN, "failed"
        )
    with library.read() as conn:
        assert resolve_track(conn, "yt:ColumnVid01") == TrackRef(BY_COLUMN, "failed")
        count = conn.execute(
            "SELECT COUNT(*) FROM track_aliases WHERE alias = 'yt:ColumnVid01'"
        ).scalar()
    assert count == 1


def test_materialize_refuses_bad_video_ids(library: Database, clock: FakeClock) -> None:
    with library.transaction() as conn, pytest.raises(InvalidId):
        materialize_song(conn, clock, CatalogTrack("../../x", "x", ()))
