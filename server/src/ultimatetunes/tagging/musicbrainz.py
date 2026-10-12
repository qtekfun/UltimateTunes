# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""MusicBrainz recording search (RF-04), one request per second.

- `https://musicbrainz.org/ws/2/recording?query=...&fmt=json`, with the User-Agent MusicBrainz
  asks for (application, version and a contact URL: the repository).
- At most one request per second for the whole worker (`musicbrainz:global` on the
  `RateLimiter`), as MusicBrainz requires. A 503/429 (MusicBrainz's "slow down") is retried
  once, after waiting for the next token and at least `Retry-After` (capped).
- Redirects are not followed. Any failure is `LookupFailedError`; the caller then keeps the
  YouTube Music data and marks the track `needs_review` (a lookup never fails a job).
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

import anyio
import httpx

from ultimatetunes import __version__
from ultimatetunes.core.ratelimit import Limit, RateLimiter
from ultimatetunes.tagging.matching import (
    Query,
    YoutubeIds,
    best_candidate,
    from_musicbrainz,
    from_youtube,
)
from ultimatetunes.tagging.model import TrackMetadata
from ultimatetunes.tagging.ratelimit import wait_for_token

log = logging.getLogger(__name__)

MUSICBRAINZ_URL = "https://musicbrainz.org/ws/2/recording"
USER_AGENT = f"UltimateTunes/{__version__} ( https://github.com/qtekfun/UltimateTunes )"
RATE_KEY = "musicbrainz:global"
ONE_PER_SECOND = Limit(rate_per_s=1.0, burst=1.0)
SEARCH_LIMIT = 10
MAX_RETRY_AFTER_S = 10.0
_SLOW_DOWN = frozenset({429, 503})


class LookupFailedError(Exception):
    """MusicBrainz could not be asked or answered something unusable."""


def _phrase(text: str) -> str:
    """A Lucene phrase: only `\\` and `"` need escaping inside quotes."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def search_query(query: Query) -> str:
    parts = [f"recording:{_phrase(query.title)}", f"artist:{_phrase(query.artist)}"]
    text = " AND ".join(parts)
    if query.album:
        # Optional: boosts the right release without excluding singles and compilations.
        text = f"({text}) OR ({text} AND release:{_phrase(query.album)})"
    return text


def _retry_after(response: httpx.Response) -> float:
    try:
        seconds = float(response.headers.get("retry-after", "1"))
    except ValueError:
        seconds = 1.0
    return max(0.0, min(MAX_RETRY_AFTER_S, seconds))


class MusicBrainz:
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

    async def _get(self, params: dict[str, str]) -> httpx.Response:
        await wait_for_token(self._limiter, RATE_KEY, ONE_PER_SECOND, self._sleep)
        try:
            return await self._client.get(
                MUSICBRAINZ_URL,
                params=params,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            raise LookupFailedError(f"MusicBrainz unreachable: {type(exc).__name__}") from exc

    async def search_recordings(self, query: Query) -> list[dict[str, Any]]:
        params = {"query": search_query(query), "fmt": "json", "limit": str(SEARCH_LIMIT)}
        response = await self._get(params)
        if response.status_code in _SLOW_DOWN:
            await self._sleep(_retry_after(response))
            response = await self._get(params)
        if response.status_code != httpx.codes.OK:
            raise LookupFailedError(f"MusicBrainz answered {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise LookupFailedError("MusicBrainz answered no JSON") from exc
        recordings = data.get("recordings") if isinstance(data, dict) else None
        if not isinstance(recordings, list):
            raise LookupFailedError("MusicBrainz answered no recordings list")
        return [rec for rec in recordings if isinstance(rec, dict)]


class MetadataResolver:
    """YouTube Music data completed with MusicBrainz when the match is strong (RF-04)."""

    def __init__(self, musicbrainz: MusicBrainz | None, min_score: float) -> None:
        self._musicbrainz = musicbrainz
        self._min_score = min_score

    async def resolve(self, query: Query, hints: YoutubeIds) -> TrackMetadata:
        if self._musicbrainz is None:
            return from_youtube(query, hints, match_score=None)
        try:
            recordings = await self._musicbrainz.search_recordings(query)
        except LookupFailedError as exc:
            log.warning("MusicBrainz lookup failed, keeping YouTube Music data: %s", exc)
            return from_youtube(query, hints, match_score=None)
        candidate = best_candidate(query, recordings)
        if candidate is None or candidate.score < self._min_score:
            return from_youtube(query, hints, match_score=candidate.score if candidate else None)
        return from_musicbrainz(query, hints, candidate)
