# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""LyricsService: stored-first lookups, LRCLIB etiquette, negative cache and the payload."""

import httpx
import pytest
import respx

from tests.lyrics.helpers import (
    MERGED_ID,
    OTHER_ID,
    TRACK_ID,
    VIDEO_ID,
    add_track,
    fixture_bytes,
)
from ultimatetunes.core.cache import MemoryTtlCache, SqliteTtlCache, TtlCache
from ultimatetunes.core.clock import FakeClock, format_ts
from ultimatetunes.core.ratelimit import SqliteRateLimiter
from ultimatetunes.db import Database
from ultimatetunes.errors import InvalidId, NotFound, UpstreamUnavailable
from ultimatetunes.lyrics.lrclib import LrclibClient
from ultimatetunes.lyrics.repository import LyricsRepository, LyricsTrack, StoredLyrics
from ultimatetunes.lyrics.service import (
    BACKOFF_KEY,
    FAILED_KEY,
    LyricsService,
    render,
)
from ultimatetunes.lyrics.settings import LyricsSettings

SYNCED = [
    {"start": 0, "value": "Salt on the window, the night coming in"},
    {"start": 4210, "value": "I keep the light for the ships that never were"},
    {"start": 9875, "value": "Turning and turning, the harbour asleep"},
]
PLAIN = [{"value": line["value"]} for line in SYNCED]


@pytest.fixture(params=["sqlite", "memory"])
def cache(request: pytest.FixtureRequest, db: Database, clock: FakeClock) -> TtlCache:
    if request.param == "sqlite":
        return SqliteTtlCache(db, clock)
    return MemoryTtlCache(clock)


@pytest.fixture
def lyrics_settings() -> LyricsSettings:
    return LyricsSettings(
        lyrics_rate_per_s=1.0,
        lyrics_burst=2.0,
        lyrics_not_found_retry_days=7,
        lyrics_failure_backoff_s=300,
    )


@pytest.fixture
def service(
    db: Database, cache: TtlCache, clock: FakeClock, lyrics_settings: LyricsSettings
) -> LyricsService:
    return LyricsService(
        db=db,
        cache=cache,
        rate_limiter=SqliteRateLimiter(db, clock),
        clock=clock,
        client=LrclibClient(),
        settings=lyrics_settings,
    )


def stored(db: Database, track_id: str = TRACK_ID) -> StoredLyrics | None:
    with db.read() as conn:
        return LyricsRepository(conn).lyrics(track_id)


def found(lrclib: respx.MockRouter, name: str = "lighthouse_keeper.json") -> respx.Route:
    return lrclib.get("/api/get").respond(200, content=fixture_bytes(name))


def test_fetches_stores_and_serves_synced_then_plain(
    service: LyricsService, db: Database, clock: FakeClock, lrclib: respx.MockRouter
) -> None:
    add_track(db, clock)
    route = found(lrclib)
    expected = [
        {
            "displayArtist": "The Paper Lanterns",
            "displayTitle": "Lighthouse Keeper",
            "lang": "und",
            "synced": True,
            "line": SYNCED,
        },
        {
            "displayArtist": "The Paper Lanterns",
            "displayTitle": "Lighthouse Keeper",
            "lang": "und",
            "synced": False,
            "line": PLAIN,
        },
    ]
    assert service.structured_lyrics(TRACK_ID) == expected
    assert dict(route.calls.last.request.url.params) == {
        "track_name": "Lighthouse Keeper",
        "artist_name": "The Paper Lanterns",
        "album_name": "Harbour Lights",
        "duration": "212",
    }
    row = stored(db)
    assert row is not None
    assert (row.source, row.source_ref, row.not_found, row.retry_after) == (
        "lrclib",
        "4242001",
        False,
        None,
    )
    assert row.fetched_at == format_ts(clock.now())
    # Stored: the second call never reaches LRCLIB.
    assert service.structured_lyrics(TRACK_ID.upper()) == expected
    assert route.call_count == 1


def test_plain_only(
    service: LyricsService, db: Database, clock: FakeClock, lrclib: respx.MockRouter
) -> None:
    add_track(db, clock, title="Quiet Pier", album=None, duration_ms=None)
    route = found(lrclib, "plain_only.json")
    result = service.structured_lyrics(TRACK_ID)
    assert [entry["synced"] for entry in result] == [False]
    assert result[0]["line"] == [
        {"value": "Gulls on the railing"},
        {"value": ""},
        {"value": "Nobody waiting"},
    ]
    assert dict(route.calls.last.request.url.params) == {
        "track_name": "Quiet Pier",
        "artist_name": "The Paper Lanterns",
    }


def test_instrumental_is_stored_as_known_without_lyrics(
    service: LyricsService, db: Database, clock: FakeClock, lrclib: respx.MockRouter
) -> None:
    add_track(db, clock)
    route = found(lrclib, "instrumental.json")
    assert service.structured_lyrics(TRACK_ID) == []
    clock.advance(400 * 86400)
    assert service.structured_lyrics(TRACK_ID) == []
    assert route.call_count == 1
    row = stored(db)
    assert row is not None
    assert not row.not_found
    assert row.source_ref == "4242003"
    assert (row.synced_lrc, row.plain_text) == (None, None)


def test_not_found_is_a_negative_entry_retried_later(
    service: LyricsService, db: Database, clock: FakeClock, lrclib: respx.MockRouter
) -> None:
    add_track(db, clock)
    route = lrclib.get("/api/get").respond(404, content=fixture_bytes("not_found.json"))
    assert service.structured_lyrics(TRACK_ID) == []
    row = stored(db)
    assert row is not None
    assert row.not_found
    assert row.retry_after == "2026-10-19T08:00:00.000Z"
    clock.advance(6 * 86400)
    assert service.structured_lyrics(TRACK_ID) == []
    assert route.call_count == 1
    # Due again: LRCLIB has it by now.
    clock.advance(86400)
    found(lrclib)
    assert len(service.structured_lyrics(TRACK_ID)) == 2
    row = stored(db)
    assert row is not None
    assert not row.not_found
    assert row.retry_after is None


def test_due_negative_entry_stays_empty_when_lrclib_fails(
    service: LyricsService, db: Database, clock: FakeClock, lrclib: respx.MockRouter
) -> None:
    add_track(db, clock)
    lrclib.get("/api/get").respond(404)
    service.structured_lyrics(TRACK_ID)
    clock.advance(8 * 86400)
    lrclib.get("/api/get").respond(500)
    assert service.structured_lyrics(TRACK_ID) == []


def test_failure_backs_off_per_track(
    service: LyricsService,
    db: Database,
    cache: TtlCache,
    clock: FakeClock,
    lrclib: respx.MockRouter,
) -> None:
    add_track(db, clock)
    add_track(db, clock, OTHER_ID, title="Quiet Pier")
    route = lrclib.get("/api/get").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(UpstreamUnavailable):
        service.structured_lyrics(TRACK_ID)
    assert cache.get(FAILED_KEY + TRACK_ID) is not None
    assert stored(db) is None
    # Within the backoff the same track does not reach LRCLIB again.
    with pytest.raises(UpstreamUnavailable, match="try again later"):
        service.structured_lyrics(TRACK_ID)
    assert route.call_count == 1
    # Another track still may.
    route.mock(side_effect=None, return_value=httpx.Response(404))
    clock.advance(1)
    assert service.structured_lyrics(OTHER_ID) == []
    assert route.call_count == 2
    clock.advance(300)
    found(lrclib)
    assert len(service.structured_lyrics(TRACK_ID)) == 2


@pytest.mark.parametrize("status", [429, 503])
def test_throttling_honours_retry_after_for_every_track(
    service: LyricsService, db: Database, clock: FakeClock, lrclib: respx.MockRouter, status: int
) -> None:
    add_track(db, clock)
    add_track(db, clock, OTHER_ID, title="Quiet Pier")
    route = lrclib.get("/api/get").respond(status, headers={"Retry-After": "30"})
    with pytest.raises(UpstreamUnavailable):
        service.structured_lyrics(TRACK_ID)
    assert service.cache.get(BACKOFF_KEY) is not None
    clock.advance(29)
    with pytest.raises(UpstreamUnavailable):
        service.structured_lyrics(OTHER_ID)
    assert route.call_count == 1
    clock.advance(1)
    found(lrclib)
    assert len(service.structured_lyrics(OTHER_ID)) == 2


def test_own_rate_limit_refuses_bursts(
    service: LyricsService, db: Database, clock: FakeClock, lrclib: respx.MockRouter
) -> None:
    ids = [f"0199d6a2-4c1e-7b3a-9f10-2a6c8e01c00{n}" for n in range(3)]
    for track_id in ids:
        add_track(db, clock, track_id)
    route = lrclib.get("/api/get").respond(404)
    service.structured_lyrics(ids[0])
    service.structured_lyrics(ids[1])
    with pytest.raises(UpstreamUnavailable, match="Too many lyrics lookups"):
        service.structured_lyrics(ids[2])
    assert route.call_count == 2
    clock.advance(1)
    assert service.structured_lyrics(ids[2]) == []
    assert route.call_count == 3


def test_tracks_without_title_or_artist_are_not_looked_up(
    service: LyricsService, db: Database, clock: FakeClock, lrclib: respx.MockRouter
) -> None:
    add_track(db, clock, artist="  ")
    add_track(db, clock, OTHER_ID, title="")
    route = lrclib.get("/api/get").respond(404)
    assert service.structured_lyrics(TRACK_ID) == []
    assert service.structured_lyrics(OTHER_ID) == []
    assert not route.called
    assert stored(db) is None


def test_yt_ids_resolve_through_aliases(
    service: LyricsService, db: Database, clock: FakeClock, lrclib: respx.MockRouter
) -> None:
    add_track(db, clock, status="pending", alias=f"yt:{VIDEO_ID}")
    found(lrclib)
    assert len(service.structured_lyrics(f"yt:{VIDEO_ID}")) == 2
    assert stored(db) is not None


def test_external_songs_answer_empty_without_lrclib(
    service: LyricsService, lrclib: respx.MockRouter
) -> None:
    route = lrclib.get("/api/get").respond(200, content=fixture_bytes("lighthouse_keeper.json"))
    assert service.structured_lyrics("yt:AAAAAAAAAAA") == []
    assert not route.called


def test_merged_tracks_resolve_to_the_surviving_track(
    service: LyricsService, db: Database, clock: FakeClock, lrclib: respx.MockRouter
) -> None:
    add_track(db, clock)
    add_track(db, clock, MERGED_ID, status="merged", merged_into=TRACK_ID)
    found(lrclib)
    assert len(service.structured_lyrics(MERGED_ID)) == 2
    assert stored(db, TRACK_ID) is not None
    assert stored(db, MERGED_ID) is None


@pytest.mark.parametrize(
    "song_id",
    [
        "yt:short",
        "yt:Qx7Lm2pZ0aB?",
        "YT:Qx7Lm2pZ0aB",
        "ytalbum:MPREb_k3Vd9QmT2xL",
        "ytartist:UCq8XbV1r0LwZ5mN3tYp7kQe",
        "al-0199d6a2-4c1e-7b3a-9f10-2a6c8e01b001",
        "../etc/passwd",
        " 0199d6a2-4c1e-7b3a-9f10-2a6c8e01b001",
    ],
)
def test_invalid_ids(service: LyricsService, song_id: str) -> None:
    with pytest.raises(InvalidId):
        service.structured_lyrics(song_id)


def test_unknown_library_id(service: LyricsService) -> None:
    with pytest.raises(NotFound):
        service.structured_lyrics("0199d6a2-4c1e-7b3a-9f10-2a6c8e01ffff")


TRACK = LyricsTrack(TRACK_ID, "ready", "T", "A", None, None, None)


def row(**changes: object) -> StoredLyrics:
    base: dict[str, object] = {
        "track_id": TRACK_ID,
        "source": "tags",
        "source_ref": None,
        "lang": "eng",
        "synced_lrc": None,
        "plain_text": None,
        "offset_ms": 0,
        "not_found": False,
        "fetched_at": "2026-10-12T08:00:00.000Z",
        "retry_after": None,
    }
    base.update(changes)
    return StoredLyrics(**base)  # type: ignore[arg-type]


def test_render_applies_offsets_and_keeps_lang() -> None:
    result = render(TRACK, row(synced_lrc="[offset:100]\n[00:01.00]a\n[00:02.00]b", offset_ms=400))
    assert result == [
        {
            "displayArtist": "A",
            "displayTitle": "T",
            "lang": "eng",
            "synced": True,
            "line": [{"start": 500, "value": "a"}, {"start": 1500, "value": "b"}],
        }
    ]


def test_render_malformed_lrc_falls_back_to_its_text() -> None:
    result = render(TRACK, row(synced_lrc="[ti:T]\nfirst\n[00:99.00]second\n"))
    assert result == [
        {
            "displayArtist": "A",
            "displayTitle": "T",
            "lang": "eng",
            "synced": False,
            "line": [{"value": "first"}, {"value": "second"}],
        }
    ]


def test_render_malformed_lrc_with_plain_text_serves_the_plain_text() -> None:
    result = render(TRACK, row(synced_lrc="garbage", plain_text="real words"))
    assert [entry["line"] for entry in result] == [[{"value": "real words"}]]


@pytest.mark.parametrize(
    "stored_row",
    [
        row(),
        row(synced_lrc="[ti:only metadata]"),
        row(plain_text="\n  \n"),
    ],
)
def test_render_nothing_to_show(stored_row: StoredLyrics) -> None:
    assert render(TRACK, stored_row) == []
