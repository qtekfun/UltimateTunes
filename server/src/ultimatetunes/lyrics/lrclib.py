# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""LRCLIB client (`GET https://lrclib.net/api/get`, documented at https://lrclib.net/docs).

Only `lrclib.net` is contacted, over HTTPS, without following redirects (CLAUDE.md: allowed
hosts). Every request names the app in `User-Agent`, as LRCLIB requires. The caller (the
service) decides how often to ask; this module turns one lookup into one of:

- an `LrclibRecord` (found; it may be instrumental or carry no lyrics at all),
- `None` (LRCLIB answered 404 `TrackNotFound`, or 400 for a query it cannot match),
- `LrclibThrottled` (429 or 503: honour `retry_after_s`),
- `LrclibUnavailable` (timeout, connection error, another status, an unreadable body).

Both errors are `UpstreamUnavailable`, so they map to OpenSubsonic error 0 if they escape.
"""

import json
import logging
from dataclasses import dataclass

import httpx

from ultimatetunes import __version__
from ultimatetunes.errors import UpstreamUnavailable

log = logging.getLogger(__name__)

BASE_URL = "https://lrclib.net"
USER_AGENT = f"UltimateTunes/{__version__} (https://github.com/qtekfun/UltimateTunes)"
# LRCLIB accepts durations from 1 to 3600 s; outside that range the duration is not sent.
MAX_DURATION_S = 3600
# An answer bigger than this is not lyrics.
MAX_BODY_BYTES = 1024 * 1024
DEFAULT_RETRY_AFTER_S = 60
MAX_RETRY_AFTER_S = 3600


class LrclibUnavailable(UpstreamUnavailable):
    default_message = "LRCLIB is unavailable"


class LrclibThrottled(LrclibUnavailable):
    default_message = "LRCLIB asked to slow down"

    def __init__(self, retry_after_s: int) -> None:
        super().__init__()
        self.retry_after_s = retry_after_s


@dataclass(frozen=True)
class LrclibQuery:
    track_name: str
    artist_name: str
    album_name: str | None = None
    duration_s: int | None = None

    def params(self) -> dict[str, str]:
        params = {"track_name": self.track_name, "artist_name": self.artist_name}
        if self.album_name:
            params["album_name"] = self.album_name
        if self.duration_s is not None and 1 <= self.duration_s <= MAX_DURATION_S:
            params["duration"] = str(self.duration_s)
        return params


@dataclass(frozen=True)
class LrclibRecord:
    id: int
    instrumental: bool
    plain_lyrics: str | None
    synced_lyrics: str | None


def retry_after(response: httpx.Response) -> int:
    """`Retry-After` in seconds, clamped to [1, 3600]; 60 when absent or not a number (the
    HTTP-date form is not worth parsing for a backoff)."""
    raw = response.headers.get("retry-after", "").strip()
    if not raw.isdigit():
        return DEFAULT_RETRY_AFTER_S
    return min(MAX_RETRY_AFTER_S, max(1, int(raw)))


def _optional_text(document: dict[str, object], name: str) -> str | None:
    value = document.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise LrclibUnavailable(f"LRCLIB field {name} is not text")
    return value or None


def parse_record(body: bytes) -> LrclibRecord:
    try:
        document = json.loads(body)
    except (ValueError, UnicodeDecodeError) as error:
        raise LrclibUnavailable("LRCLIB answered something that is not JSON") from error
    if not isinstance(document, dict):
        raise LrclibUnavailable("LRCLIB answered an unexpected document")
    record_id = document.get("id")
    if not isinstance(record_id, int) or isinstance(record_id, bool):
        raise LrclibUnavailable("LRCLIB record without an id")
    return LrclibRecord(
        id=record_id,
        instrumental=document.get("instrumental") is True,
        plain_lyrics=_optional_text(document, "plainLyrics"),
        synced_lyrics=_optional_text(document, "syncedLyrics"),
    )


class LrclibClient:
    def __init__(
        self, *, timeout_s: float = 5.0, transport: httpx.BaseTransport | None = None
    ) -> None:
        self._timeout = httpx.Timeout(timeout_s)
        self._transport = transport

    def get(self, query: LrclibQuery) -> LrclibRecord | None:
        try:
            with httpx.Client(
                base_url=BASE_URL,
                timeout=self._timeout,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                follow_redirects=False,
                transport=self._transport,
            ) as client:
                response = client.get("/api/get", params=query.params())
        except httpx.HTTPError as error:
            raise LrclibUnavailable("LRCLIB did not answer") from error
        status = response.status_code
        if status == httpx.codes.NOT_FOUND:
            return None
        if status == httpx.codes.BAD_REQUEST:
            log.warning("LRCLIB refused a lyrics query (HTTP 400)")
            return None
        if status in (httpx.codes.TOO_MANY_REQUESTS, httpx.codes.SERVICE_UNAVAILABLE):
            raise LrclibThrottled(retry_after(response))
        if status != httpx.codes.OK:
            raise LrclibUnavailable(f"LRCLIB answered HTTP {status}")
        if len(response.content) > MAX_BODY_BYTES:
            raise LrclibUnavailable("LRCLIB answer too large")
        return parse_record(response.content)
