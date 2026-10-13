# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""MusicBrainz client (respx, no network): User-Agent, query, 1 req/s, retry, fallbacks."""

from typing import Any

import httpx
import pytest
import respx

from ultimatetunes.core.clock import FakeClock
from ultimatetunes.tagging.matching import Query, YoutubeIds
from ultimatetunes.tagging.musicbrainz import (
    MAX_BODY_BYTES,
    MUSICBRAINZ_URL,
    USER_AGENT,
    LookupFailedError,
    MetadataResolver,
    MusicBrainz,
    search_query,
)
from ultimatetunes.tagging.ratelimit import MemoryRateLimiter

pytestmark = pytest.mark.anyio
QUERY = Query("Paper Moons (Live)", "The Paper Lanterns", "Lanterns at Dusk", 262000)


class Sleeper:
    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.slept: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.clock.advance(seconds)


def make(client: httpx.AsyncClient) -> tuple[MusicBrainz, Sleeper]:
    clock = FakeClock()
    sleeper = Sleeper(clock)
    return MusicBrainz(client, MemoryRateLimiter(clock), sleep=sleeper), sleeper


def test_the_query_quotes_and_escapes() -> None:
    assert search_query(Query('Say "Hi" \\o/', "A", None, None)) == (
        'recording:"Say \\"Hi\\" \\\\o/" AND artist:"A"'
    )
    assert search_query(QUERY) == (
        '(recording:"Paper Moons (Live)" AND artist:"The Paper Lanterns") OR '
        '(recording:"Paper Moons (Live)" AND artist:"The Paper Lanterns"'
        ' AND release:"Lanterns at Dusk")'
    )


async def test_search_sends_the_user_agent_and_paces_requests(
    web: respx.MockRouter, mb_search: dict[str, Any]
) -> None:
    route = web.get(MUSICBRAINZ_URL).respond(200, json=mb_search)
    async with httpx.AsyncClient() as client:
        musicbrainz, sleeper = make(client)
        for _ in range(3):
            found = await musicbrainz.search_recordings(QUERY)
    assert len(found) == 2  # the non-object entry is dropped
    request = route.calls[0].request
    assert request.headers["user-agent"] == USER_AGENT
    assert "github.com/qtekfun/UltimateTunes" in USER_AGENT
    assert request.url.params["fmt"] == "json"
    assert request.url.params["query"] == search_query(QUERY)
    assert sleeper.slept == [1, 1]  # one request per second


async def test_slow_down_is_retried_once(web: respx.MockRouter, mb_search: dict[str, Any]) -> None:
    web.get(MUSICBRAINZ_URL).mock(
        side_effect=[
            httpx.Response(503, headers={"Retry-After": "120"}),
            httpx.Response(200, json=mb_search),
        ]
    )
    async with httpx.AsyncClient() as client:
        musicbrainz, sleeper = make(client)
        assert len(await musicbrainz.search_recordings(QUERY)) == 2
    assert sleeper.slept == [10.0]  # Retry-After capped; the token refilled meanwhile


@pytest.mark.parametrize(
    "responses",
    [
        [httpx.Response(429, headers={"Retry-After": "soon"}), httpx.Response(429)],
        [httpx.Response(301, headers={"Location": "https://evil.example/"})],
        [httpx.Response(200, text="<html>")],
        [httpx.Response(200, json={"recordings": "x"})],
        [httpx.Response(200, json=[1])],
        [httpx.ConnectError("down")],
    ],
)
async def test_failures_are_lookup_failures(web: respx.MockRouter, responses: list[Any]) -> None:
    web.get(MUSICBRAINZ_URL).mock(side_effect=responses)
    async with httpx.AsyncClient() as client:
        musicbrainz, _ = make(client)
        with pytest.raises(LookupFailedError):
            await musicbrainz.search_recordings(QUERY)


async def test_the_resolver_keeps_youtube_data_unless_the_match_is_strong(
    web: respx.MockRouter, mb_search: dict[str, Any]
) -> None:
    route = web.get(MUSICBRAINZ_URL)
    hints = YoutubeIds(album_browse_id="MPREb_k3Vd9QmT2xL")
    async with httpx.AsyncClient() as client:
        musicbrainz, _ = make(client)
        route.respond(200, json=mb_search)
        strong = await MetadataResolver(musicbrainz, 0.85).resolve(QUERY, hints)
        assert (strong.needs_review, strong.musicbrainz.recording_id) == (
            False,
            "2b4d6f8a-1c3e-4a5b-9d7f-0e2c4a6b8d01",
        )
        other = Query("Lantern Song", "Somebody Else", None, 100000)
        weak = await MetadataResolver(musicbrainz, 0.85).resolve(other, hints)
        assert weak.needs_review
        assert weak.match_score is not None
        assert weak.musicbrainz.recording_id is None
        route.respond(200, json={"recordings": []})
        none = await MetadataResolver(musicbrainz, 0.85).resolve(QUERY, hints)
        assert (none.needs_review, none.match_score) == (True, None)
        route.respond(500)
        failed = await MetadataResolver(musicbrainz, 0.85).resolve(QUERY, hints)
        assert (failed.needs_review, failed.album_browse_id) == (True, "MPREb_k3Vd9QmT2xL")
    off = await MetadataResolver(None, 0.85).resolve(QUERY, hints)
    assert off.needs_review


async def test_huge_answers_are_refused(web: respx.MockRouter) -> None:
    web.get(MUSICBRAINZ_URL).respond(200, content=b" " * (MAX_BODY_BYTES + 1))
    async with httpx.AsyncClient() as client:
        musicbrainz, _ = make(client)
        with pytest.raises(LookupFailedError, match="too large"):
            await musicbrainz.search_recordings(QUERY)


async def test_a_weak_strict_search_is_followed_by_one_loose_search(
    web: respx.MockRouter, mb_search: dict[str, Any]
) -> None:
    route = web.get(MUSICBRAINZ_URL)
    route.mock(
        side_effect=[
            httpx.Response(200, json={"recordings": [mb_search["recordings"][1]]}),
            httpx.Response(200, json=mb_search),
        ]
    )
    async with httpx.AsyncClient() as client:
        musicbrainz, sleeper = make(client)
        meta = await MetadataResolver(musicbrainz, 0.85).resolve(QUERY, YoutubeIds())
    assert (meta.needs_review, meta.musicbrainz.recording_id) == (
        False,
        "2b4d6f8a-1c3e-4a5b-9d7f-0e2c4a6b8d01",
    )
    sent = [call.request.url.params["query"] for call in route.calls]
    assert sent == [search_query(QUERY), search_query(QUERY, loose=True)]
    assert sleeper.slept == [1]  # the second request still waits for its token


async def test_a_failed_loose_search_keeps_the_strict_candidate(
    web: respx.MockRouter, mb_search: dict[str, Any]
) -> None:
    weak = mb_search["recordings"][1]
    web.get(MUSICBRAINZ_URL).mock(
        side_effect=[httpx.Response(200, json={"recordings": [weak]}), httpx.Response(500)]
    )
    async with httpx.AsyncClient() as client:
        musicbrainz, _ = make(client)
        meta = await MetadataResolver(musicbrainz, 0.85).resolve(QUERY, YoutubeIds())
    assert meta.needs_review
    assert meta.match_score is not None
    assert meta.match_score < 0.85
