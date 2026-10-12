# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Album covers: Cover Art Archive first, the YouTube thumbnail as a fallback (contracts/ids.md).

- Cover Art Archive: `https://coverartarchive.org/release/<mbid>/front-500`, then the release
  group's front. CAA answers with a redirect to its storage on the Internet Archive, so
  redirects are followed by hand, HTTPS only, at most `MAX_REDIRECTS`, and only to
  `coverartarchive.org`, `archive.org` and its subdomains (where CAA keeps the images).
- YouTube thumbnail: the URL the catalog returned (never client input), HTTPS only, the exact
  approved hosts, **no redirects**.
- Both: `image/*` content type, at most 5 MiB enforced while streaming, and a JPEG body
  (the cover is stored as `cover.jpg`; no image library is approved to convert others).
- Any failure is just "no cover" (logged); a cover never fails a job.
"""

import logging
import re
from collections.abc import Callable
from urllib.parse import urljoin, urlsplit

import httpx

from ultimatetunes.tagging.musicbrainz import USER_AGENT

log = logging.getLogger(__name__)

CAA_ROOT = "https://coverartarchive.org"
YOUTUBE_IMAGE_HOSTS = frozenset(
    {"i.ytimg.com", "lh3.googleusercontent.com", "yt3.ggpht.com", "yt3.googleusercontent.com"}
)
MAX_COVER_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 3
JPEG_MAGIC = b"\xff\xd8\xff"
_MBID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_REDIRECTS = frozenset({301, 302, 303, 307, 308})
HostCheck = Callable[[str], bool]


class CoverRejectedError(Exception):
    """The answer is not an acceptable cover (host, redirect, type, size, format)."""


def caa_host(host: str) -> bool:
    return host in ("coverartarchive.org", "archive.org") or host.endswith(".archive.org")


def youtube_host(host: str) -> bool:
    return host in YOUTUBE_IMAGE_HOSTS


def _checked(url: str, allowed: HostCheck) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.port not in (None, 443) or parts.username:
        raise CoverRejectedError("not a plain https URL")
    if not allowed(parts.hostname or ""):
        raise CoverRejectedError(f"host {parts.hostname!r} is not allowed")
    return url


class CoverFetcher:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def _download(self, url: str, allowed: HostCheck, redirects: int) -> bytes:
        for _ in range(redirects + 1):
            async with self._client.stream(
                "GET",
                _checked(url, allowed),
                headers={"User-Agent": USER_AGENT, "Accept": "image/jpeg,image/*"},
                follow_redirects=False,
            ) as response:
                if response.status_code in _REDIRECTS and "location" in response.headers:
                    url = urljoin(url, response.headers["location"])
                    continue
                if response.status_code != httpx.codes.OK:
                    raise CoverRejectedError(f"answered {response.status_code}")
                content_type = response.headers.get("content-type", "")
                if not content_type.lower().startswith("image/"):
                    raise CoverRejectedError("not an image")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_COVER_BYTES:
                        raise CoverRejectedError("larger than 5 MiB")
                if not body.startswith(JPEG_MAGIC):
                    raise CoverRejectedError("not a JPEG")
                return bytes(body)
        raise CoverRejectedError("too many redirects")

    async def _try(self, url: str, allowed: HostCheck, redirects: int) -> bytes | None:
        try:
            return await self._download(url, allowed, redirects)
        except CoverRejectedError as exc:
            log.info("no cover from %s: %s", urlsplit(url).hostname, exc)
        except httpx.HTTPError as exc:
            log.info("no cover from %s: %s", urlsplit(url).hostname, type(exc).__name__)
        return None

    async def fetch(
        self,
        *,
        release_id: str | None,
        release_group_id: str | None,
        thumbnail_url: str | None,
    ) -> bytes | None:
        """The best cover, or None."""
        for kind, mbid in (("release", release_id), ("release-group", release_group_id)):
            if mbid is not None and _MBID.fullmatch(mbid):
                url = f"{CAA_ROOT}/{kind}/{mbid}/front-500"
                found = await self._try(url, caa_host, MAX_REDIRECTS)
                if found is not None:
                    return found
        if thumbnail_url:
            return await self._try(thumbnail_url, youtube_host, 0)
        return None
