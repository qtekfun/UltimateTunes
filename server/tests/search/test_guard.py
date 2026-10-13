# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`GuardedCatalog`: cache, negative cache, single flight, rate limit, retry, circuit breaker."""

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

import pytest

from ultimatetunes.core.cache import SqliteTtlCache
from ultimatetunes.core.caller import ANONYMOUS, current_bucket, set_caller, unmetered
from ultimatetunes.core.clock import FakeClock
from ultimatetunes.core.inflight import MemoryInFlight
from ultimatetunes.core.ratelimit import SqliteRateLimiter
from ultimatetunes.db import Database
from ultimatetunes.errors import RateLimited, TunesError
from ultimatetunes.search.catalog import (
    CatalogClientError,
    CatalogNotFound,
    CatalogParseError,
    CatalogThrottled,
    CatalogTrack,
    CatalogUnavailable,
)
from ultimatetunes.search.fake import PLAYLIST_ID, FakeMusicCatalog
from ultimatetunes.search.guard import (
    BREAKER_LEVEL,
    BREAKER_OPEN,
    BUCKET,
    TTL_NOT_FOUND,
    BreakerState,
    GuardedCatalog,
    _jitter,
)
from ultimatetunes.search.settings import SearchSettings

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class Scripted(FakeMusicCatalog):
    """The fake catalog, but each call first pops an error from `errors` (if any)."""

    def __init__(self) -> None:
        super().__init__()
        self.errors: list[TunesError] = []
        self.gate: asyncio.Event | None = None

    async def search_songs(self, query: str, limit: int) -> list[CatalogTrack]:
        if self.gate is not None:
            await self.gate.wait()
        if self.errors:
            self.calls.append("search_songs")
            raise self.errors.pop(0)
        return await super().search_songs(query, limit)


class Harness:
    def __init__(self, db: Database, clock: FakeClock, **settings: float) -> None:
        self.inner = Scripted()
        self.clock = clock
        self.cache = SqliteTtlCache(db, clock)
        self.limiter = SqliteRateLimiter(db, clock)
        self.slept: list[float] = []
        self.catalog = GuardedCatalog(
            self.inner,
            cache=self.cache,
            limiter=self.limiter,
            inflight=MemoryInFlight(),
            settings=SearchSettings(**settings),  # type: ignore[arg-type]
            sleep=self.sleep,
            jitter=lambda: 0.75,
        )

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.clock.advance(seconds)


@pytest.fixture
def h(db: Database, clock: FakeClock) -> Harness:
    return Harness(db, clock)


def inner_calls(h: Harness, name: str) -> int:
    return h.inner.calls.count(name)


async def test_results_are_cached_per_normalised_query(h: Harness) -> None:
    first = await h.catalog.search_songs("Lanterns", 2)
    assert len(first) == 2
    again = await h.catalog.search_songs("  LANTERNS ", 20)
    assert len(again) == 4
    assert inner_calls(h, "search_songs") == 1
    # Search results also fill the track cache: no request for a known song.
    assert (await h.catalog.track(first[0].video_id)) == first[0]
    assert inner_calls(h, "track") == 0
    h.clock.advance(24 * 3600)
    await h.catalog.search_songs("lanterns", 1)
    assert inner_calls(h, "search_songs") == 2


async def test_every_call_is_cached(h: Harness) -> None:
    calls: list[Callable[[], Awaitable[object]]] = [
        lambda: h.catalog.search_albums("dusk", 5),
        lambda: h.catalog.search_artists("harbor", 5),
        lambda: h.catalog.album("MPREb_k3Vd9QmT2xL"),
        lambda: h.catalog.artist("UCq8XbV1r0LwZ5mN3tYp7kQe"),
        lambda: h.catalog.track("Hm3Vx8Nq2Lp"),
        lambda: h.catalog.radio("Fk2Lp9QwXa1", 3),
        lambda: h.catalog.playlist(PLAYLIST_ID),
    ]
    first = [await call() for call in calls]
    count = len(h.inner.calls)
    assert [await call() for call in calls] == first
    assert len(h.inner.calls) == count
    assert len(await h.catalog.radio("Fk2Lp9QwXa1", 2)) == 2


async def test_charts_moods_and_mood_tracks_are_cached(h: Harness) -> None:
    from ultimatetunes.search.fake import MOODS  # noqa: PLC0415

    assert len(await h.catalog.charts("ES")) >= 1
    assert await h.catalog.charts("ES") == await h.catalog.charts("ES")
    assert inner_calls(h, "charts") == 1
    assert [m.title for m in await h.catalog.moods()] == ["Chill", "Focus"]
    await h.catalog.moods()
    assert inner_calls(h, "moods") == 1
    tracks = await h.catalog.mood_tracks(MOODS[0].params)
    assert len(tracks) == 2
    assert await h.catalog.mood_tracks(MOODS[0].params) == tracks
    assert inner_calls(h, "mood_tracks") == 1
    # A different country is a different cache key.
    await h.catalog.charts("ZZ")
    assert inner_calls(h, "charts") == 2


async def test_unknown_ids_are_cached_as_not_found(h: Harness) -> None:
    for _ in range(2):
        with pytest.raises(CatalogNotFound):
            await h.catalog.album("MPREb_unknown")
    assert inner_calls(h, "album") == 1
    h.clock.advance(TTL_NOT_FOUND)
    with pytest.raises(CatalogNotFound):
        await h.catalog.album("MPREb_unknown")
    assert inner_calls(h, "album") == 2


async def test_unreadable_cache_entries_are_refetched(h: Harness) -> None:
    h.cache.set("album:MPREb_k3Vd9QmT2xL", '{"layout": "old"}', 60)
    album = await h.catalog.album("MPREb_k3Vd9QmT2xL")
    assert album.ref.title == "Lanterns at Dusk"
    assert inner_calls(h, "album") == 1


async def test_concurrent_identical_calls_share_one_request(h: Harness) -> None:
    h.inner.gate = asyncio.Event()
    calls = [asyncio.ensure_future(h.catalog.search_songs("night", 5)) for _ in range(3)]
    await asyncio.sleep(0.01)
    h.inner.gate.set()
    results = await asyncio.gather(*calls)
    assert results[0] == results[1] == results[2]
    assert inner_calls(h, "search_songs") == 1


async def test_one_retry_on_unavailable(h: Harness) -> None:
    h.inner.errors = [CatalogUnavailable()]
    assert await h.catalog.search_songs("night", 5)
    assert h.slept == [0.75]
    h.inner.errors = [CatalogUnavailable(), CatalogUnavailable()]
    with pytest.raises(CatalogUnavailable):
        await h.catalog.search_songs("ferry", 5)
    assert inner_calls(h, "search_songs") == 4


async def test_parse_errors_are_not_retried(h: Harness) -> None:
    h.inner.errors = [CatalogParseError()]
    with pytest.raises(CatalogParseError):
        await h.catalog.search_songs("night", 5)
    assert inner_calls(h, "search_songs") == 1
    assert h.slept == []


async def test_refused_requests_are_not_retried(h: Harness) -> None:
    h.inner.errors = [CatalogClientError()]
    with pytest.raises(CatalogClientError) as raised:
        await h.catalog.search_songs("night", 5)
    # Callers that only know `CatalogUnavailable` still catch it.
    assert isinstance(raised.value, CatalogUnavailable)
    assert inner_calls(h, "search_songs") == 1
    assert h.slept == []
    assert await h.catalog.breaker_state() == BreakerState(open=False, level=0)


async def test_throttling_opens_the_breaker(h: Harness) -> None:
    await h.catalog.search_songs("night", 5)
    h.inner.errors = [CatalogThrottled()]
    with pytest.raises(CatalogThrottled):
        await h.catalog.search_songs("ferry", 5)
    assert await h.catalog.breaker_state() == BreakerState(open=True, level=1)
    # Open: uncached calls fail fast, cached ones still answer.
    with pytest.raises(CatalogThrottled):
        await h.catalog.search_songs("orchard", 5)
    assert await h.catalog.search_songs("night", 5)
    assert inner_calls(h, "search_songs") == 2
    # Closed again after 5 minutes; throttled again soon after: 10 minutes.
    h.clock.advance(300)
    assert (await h.catalog.breaker_state()).open is False
    h.inner.errors = [CatalogThrottled()]
    with pytest.raises(CatalogThrottled):
        await h.catalog.search_songs("orchard", 5)
    assert await h.catalog.breaker_state() == BreakerState(open=True, level=2)
    h.clock.advance(300)
    assert (await h.catalog.breaker_state()).open is True
    h.clock.advance(300)
    # A success resets the escalation.
    assert await h.catalog.search_songs("orchard", 5)
    assert await h.catalog.breaker_state() == BreakerState(open=False, level=0)


async def test_breaker_duration_is_capped(db: Database, clock: FakeClock) -> None:
    h = Harness(db, clock, ytm_breaker_base_s=1000, ytm_breaker_max_s=1500)
    h.cache.set(BREAKER_LEVEL, "1", 9999)
    h.inner.errors = [CatalogThrottled()]
    with pytest.raises(CatalogThrottled):
        await h.catalog.search_songs("night", 5)
    h.clock.advance(1499)
    assert (await h.catalog.breaker_state()).open is True
    h.clock.advance(1)
    assert await h.catalog.breaker_state() == BreakerState(open=False, level=2)


async def test_unreadable_breaker_level_counts_as_zero(h: Harness) -> None:
    h.cache.set(BREAKER_LEVEL, "not a number", 60)
    assert await h.catalog.breaker_state() == BreakerState(open=False, level=0)
    h.cache.set(BREAKER_OPEN, "1", 60)
    assert (await h.catalog.breaker_state()).open is True


async def test_rate_limit_waits_then_gives_up(db: Database, clock: FakeClock) -> None:
    h = Harness(db, clock, ytm_rate_per_s=1, ytm_burst=1, ytm_max_wait_s=1)
    await h.catalog.search_songs("night", 5)
    # The bucket is empty: wait one second for the next token.
    await h.catalog.search_songs("ferry", 5)
    assert h.slept == [1]
    # Locked out (an admin, or another limiter user): waiting longer than allowed fails.
    h.limiter.record_failure(BUCKET, max_failures=1, lockout_s=30)
    with pytest.raises(CatalogUnavailable):
        await h.catalog.search_songs("orchard", 5)
    assert inner_calls(h, "search_songs") == 2


def test_jitter_range() -> None:
    values = {_jitter() for _ in range(200)}
    assert all(0.5 <= v <= 1.5 for v in values)
    assert len(values) > 1


# ---------------------------------------------------------------- per-user catalog budget
# Each test body runs in a task of its own, so the caller it sets never leaks into other tests.


def budget(db: Database, clock: FakeClock, burst: float = 2) -> Harness:
    return Harness(db, clock, catalog_user_rate_per_s=0.01, catalog_user_burst=burst)


async def isolated(body: Callable[[], Coroutine[Any, Any, None]]) -> None:
    await asyncio.create_task(body())


async def test_every_uncached_lookup_is_charged_to_its_caller(
    db: Database, clock: FakeClock
) -> None:
    h = budget(db, clock)

    async def body() -> None:
        set_caller("user-a")
        await h.catalog.track("Fk2Lp9QwXa1")
        await h.catalog.album("MPREb_Hn2Vq8Lr5Tz")
        with pytest.raises(RateLimited) as refused:
            await h.catalog.artist("UCq8XbV1r0LwZ5mN3tYp7kQe")
        assert refused.value.retry_after_s > 0
        assert inner_calls(h, "artist") == 0
        # Cached answers cost nothing (the album filled `track:` entries too).
        await h.catalog.track("Fk2Lp9QwXa1")
        await h.catalog.track("Hm3Vx8Nq2Lp")
        await h.catalog.album("MPREb_Hn2Vq8Lr5Tz")
        # A cached not-found costs nothing either.
        set_caller("user-b")
        with pytest.raises(CatalogNotFound):
            await h.catalog.track("NoSuchVid00")
        set_caller("user-a")
        with pytest.raises(CatalogNotFound):
            await h.catalog.track("NoSuchVid00")
        # Another user has a budget of its own.
        set_caller("user-b")
        await h.catalog.radio("Fk2Lp9QwXa1", 5)
        with pytest.raises(RateLimited):
            await h.catalog.playlist(PLAYLIST_ID)

    await isolated(body)


async def test_anonymous_callers_share_one_bucket(db: Database, clock: FakeClock) -> None:
    h = budget(db, clock, burst=1)

    async def body() -> None:
        assert current_bucket() == ANONYMOUS
        await h.catalog.track("Fk2Lp9QwXa1")
        set_caller(None)
        assert current_bucket() == ANONYMOUS
        with pytest.raises(RateLimited):
            await h.catalog.track("Rb8Tn3ZcYv0")
        set_caller("user-a")
        await h.catalog.track("Rb8Tn3ZcYv0")

    await isolated(body)


async def test_searches_and_unmetered_work_are_not_charged(db: Database, clock: FakeClock) -> None:
    h = budget(db, clock, burst=1)

    async def body() -> None:
        set_caller("user-a")
        for query in ("lantern", "harbor", "static"):
            await h.catalog.search_songs(query, 5)
            await h.catalog.search_albums(query, 5)
            await h.catalog.search_artists(query, 5)
        with unmetered():
            assert current_bucket() is None
            await h.catalog.album("MPREb_k3Vd9QmT2xL")
            await h.catalog.album("MPREb_Hn2Vq8Lr5Tz")
        assert current_bucket() == "user-a"
        await h.catalog.artist("UCq8XbV1r0LwZ5mN3tYp7kQe")

    await isolated(body)


async def test_the_caller_does_not_leak_into_other_tasks() -> None:
    seen: list[str | None] = []

    async def request(user: str) -> None:
        set_caller(user)
        await asyncio.sleep(0)
        seen.append(current_bucket())

    await asyncio.gather(request("a"), request("b"))
    assert sorted(b or "" for b in seen) == ["a", "b"]
    assert current_bucket() == ANONYMOUS
