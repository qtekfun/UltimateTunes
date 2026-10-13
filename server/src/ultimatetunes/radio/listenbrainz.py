# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""ListenBrainz read-only lookups (RF-06), one request per second.

`https://api.listenbrainz.org/1/popularity/top-recordings-for-artist/<artist_mbid>` returns an
artist's most-listened recordings across the MetaBrainz community (CC0 data). This is a
**public, no-auth, read-only** endpoint: only a public MusicBrainz artist id is sent, never the
caller's listening history, so nothing private leaves the server (SPEC §11, MetaBrainz social
contract — public-domain/CC0 data, non-commercial self-hosted use allowed).

Safety (CLAUDE.md), like `tagging/musicbrainz.py` and `library/covers.py`:
- HTTPS to the exact host `api.listenbrainz.org`; the host is constant, never client input
  (no SSRF). Redirects are not followed; `trust_env=False`; no credentials.
- The artist id must match the MusicBrainz UUID shape before any request.
- At most one request per second for the whole api (`listenbrainz:global`), as ListenBrainz
  requires; a 429 is not retried (the caller degrades). The User-Agent carries the application
  and a contact URL, as ListenBrainz requires.
- The body is read only on 200 and capped. Any failure is `ListenBrainzError`; the recommender
  then returns no ListenBrainz shelf and the rest of the recommendations still come back.
"""

import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import anyio
import httpx

from ultimatetunes import __version__
from ultimatetunes.core.ratelimit import Limit, RateLimiter
from ultimatetunes.tagging.ratelimit import wait_for_token

log = logging.getLogger(__name__)

TOP_RECORDINGS_URL = (
    "https://api.listenbrainz.org/1/popularity/top-recordings-for-artist/{artist_mbid}"
)
USER_AGENT = f"UltimateTunes/{__version__} ( https://github.com/qtekfun/UltimateTunes )"
RATE_KEY = "listenbrainz:global"
ONE_PER_SECOND = Limit(rate_per_s=1.0, burst=1.0)
# A list of popular recordings fits in well under this.
MAX_BODY_BYTES = 1 * 1024 * 1024
_MBID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_HTTP_OK = 200


class ListenBrainzError(Exception):
    """ListenBrainz could not be asked or answered something unusable."""


@dataclass(frozen=True)
class LbRecording:
    recording_name: str
    artist_name: str


def default_client(timeout_s: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(follow_redirects=False, timeout=timeout_s, trust_env=False)


class ListenBrainz:
    def __init__(
        self,
        client: httpx.AsyncClient,
        limiter: RateLimiter,
        *,
        sleep: Callable[[float], Awaitable[None]] = anyio.sleep,
    ) -> None:
        self._client = client
        self._limiter = limiter
        self._sleep = sleep

    async def top_recordings_for_artist(self, artist_mbid: str, limit: int) -> list[LbRecording]:
        """The artist's most-listened recordings on ListenBrainz, best first, at most `limit`."""
        if _MBID.fullmatch(artist_mbid) is None:
            raise ListenBrainzError("not a MusicBrainz artist id")
        await wait_for_token(self._limiter, RATE_KEY, ONE_PER_SECOND, self._sleep)
        url = TOP_RECORDINGS_URL.format(artist_mbid=artist_mbid)
        try:
            async with self._client.stream(
                "GET",
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                follow_redirects=False,
            ) as response:
                body = bytearray()
                if response.status_code == _HTTP_OK:
                    async for chunk in response.aiter_bytes():
                        body += chunk
                        if len(body) > MAX_BODY_BYTES:
                            raise ListenBrainzError("ListenBrainz answer is too large")
                status = response.status_code
        except httpx.HTTPError as exc:
            raise ListenBrainzError(f"ListenBrainz unreachable: {type(exc).__name__}") from exc
        if status != _HTTP_OK:
            raise ListenBrainzError(f"ListenBrainz answered {status}")
        return _parse(bytes(body), limit)


def _parse(body: bytes, limit: int) -> list[LbRecording]:
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise ListenBrainzError("ListenBrainz answered no JSON") from exc
    if not isinstance(data, list):
        raise ListenBrainzError("ListenBrainz answered no recordings list")
    found: list[LbRecording] = []
    for item in data:
        recording = _recording(item)
        if recording is not None:
            found.append(recording)
        if len(found) >= limit:
            break
    return found


def _recording(item: Any) -> LbRecording | None:
    if not isinstance(item, dict):
        return None
    name = item.get("recording_name")
    artist = item.get("artist_name")
    if not isinstance(name, str) or not name.strip():
        return None
    if not isinstance(artist, str) or not artist.strip():
        return None
    return LbRecording(name.strip(), artist.strip())
