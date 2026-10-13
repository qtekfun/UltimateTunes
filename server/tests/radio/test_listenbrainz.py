# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""ListenBrainz client (respx, no network): host, User-Agent, 1 req/s, failures, parsing."""

from collections.abc import Iterator

import httpx
import pytest
import respx

from ultimatetunes.core.clock import FakeClock
from ultimatetunes.radio.listenbrainz import (
    MAX_BODY_BYTES,
    TOP_RECORDINGS_URL,
    USER_AGENT,
    LbRecording,
    ListenBrainz,
    ListenBrainzError,
)
from ultimatetunes.tagging.ratelimit import MemoryRateLimiter

pytestmark = pytest.mark.anyio
MBID = "8f6bd1e4-fbe1-4f50-aa9b-94c450ec0f11"
URL = TOP_RECORDINGS_URL.format(artist_mbid=MBID)
# Trimmed real shape (public music metadata only, no personal data).
RECORDINGS = [
    {"recording_name": "Closer", "artist_name": "Nine Inch Nails", "total_listen_count": 1380798},
    {"recording_name": "Hurt", "artist_name": "Nine Inch Nails", "total_listen_count": 900000},
    {"artist_name": "No name"},
    "not a dict",
    {"recording_name": "   ", "artist_name": "Blank"},
]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def web() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as router:
        yield router


class Sleeper:
    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.slept: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.clock.advance(seconds)


def make(client: httpx.AsyncClient) -> tuple[ListenBrainz, Sleeper]:
    clock = FakeClock()
    sleeper = Sleeper(clock)
    return ListenBrainz(client, MemoryRateLimiter(clock), sleep=sleeper), sleeper


async def test_success_sends_user_agent_and_paces(web: respx.MockRouter) -> None:
    route = web.get(URL).respond(200, json=RECORDINGS)
    async with httpx.AsyncClient() as client:
        lb, sleeper = make(client)
        first = await lb.top_recordings_for_artist(MBID, 10)
        second = await lb.top_recordings_for_artist(MBID, 10)
    assert first == [
        LbRecording("Closer", "Nine Inch Nails"),
        LbRecording("Hurt", "Nine Inch Nails"),
    ]
    assert first == second
    request = route.calls[0].request
    assert request.headers["user-agent"] == USER_AGENT
    assert "github.com/qtekfun/UltimateTunes" in USER_AGENT
    assert request.url.host == "api.listenbrainz.org"
    assert sleeper.slept == [1]  # one request per second


async def test_limit_truncates(web: respx.MockRouter) -> None:
    web.get(URL).respond(200, json=RECORDINGS)
    async with httpx.AsyncClient() as client:
        lb, _ = make(client)
        found = await lb.top_recordings_for_artist(MBID, 1)
    assert found == [LbRecording("Closer", "Nine Inch Nails")]


async def test_a_bad_artist_id_never_makes_a_request(web: respx.MockRouter) -> None:
    route = web.get(URL).respond(200, json=RECORDINGS)
    async with httpx.AsyncClient() as client:
        lb, _ = make(client)
        for bad in ("not-a-mbid", "8f6bd1e4fbe14f50aa9b94c450ec0f11", ""):
            with pytest.raises(ListenBrainzError):
                await lb.top_recordings_for_artist(bad, 10)
    assert not route.called


@pytest.mark.parametrize("status", [404, 429, 500, 503])
async def test_non_200_is_an_error(web: respx.MockRouter, status: int) -> None:
    web.get(URL).respond(status, json=[])
    async with httpx.AsyncClient() as client:
        lb, _ = make(client)
        with pytest.raises(ListenBrainzError):
            await lb.top_recordings_for_artist(MBID, 10)


@pytest.mark.parametrize("body", [b"not json", b'{"not": "a list"}'])
async def test_unusable_body_is_an_error(web: respx.MockRouter, body: bytes) -> None:
    web.get(URL).respond(200, content=body)
    async with httpx.AsyncClient() as client:
        lb, _ = make(client)
        with pytest.raises(ListenBrainzError):
            await lb.top_recordings_for_artist(MBID, 10)


async def test_huge_answers_are_refused(web: respx.MockRouter) -> None:
    web.get(URL).respond(200, content=b"[" + b" " * (MAX_BODY_BYTES + 1))
    async with httpx.AsyncClient() as client:
        lb, _ = make(client)
        with pytest.raises(ListenBrainzError):
            await lb.top_recordings_for_artist(MBID, 10)


async def test_network_error_is_an_error(web: respx.MockRouter) -> None:
    web.get(URL).mock(side_effect=httpx.ConnectError("down"))
    async with httpx.AsyncClient() as client:
        lb, _ = make(client)
        with pytest.raises(ListenBrainzError):
            await lb.top_recordings_for_artist(MBID, 10)
