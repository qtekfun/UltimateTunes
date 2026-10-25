# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The canary checks (SPEC section 11): does YouTube Music still answer the way we parse it,
and does yt-dlp still download?

- `CatalogCanary` (api side, ytmusicapi): one search, one radio, one album page and one
  playlist read, straight to the catalog (never through the api's cache, which would hide a
  breakage for days).
- `DownloadCanary` (worker side, yt-dlp): one download of the fixed Creative Commons track
  into its own staging directory (`canary/<random>`), checked and **always deleted**: a
  canary download is never tagged, registered or archived.

Each check is bounded by a timeout and never raises: a failure becomes a failed `Check` with
a short message (no URLs, no secrets), and a catalog parse error says "layout changed", the
alert SPEC section 11 reserves for canary runs.
"""

import json
import logging
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

import anyio

from ultimatetunes.core.clock import Clock, format_ts
from ultimatetunes.core.storage import StagingStore
from ultimatetunes.errors import TunesError
from ultimatetunes.search.catalog import CatalogParseError, MusicCatalog
from ultimatetunes.settings import Settings
from ultimatetunes.worker.client import ApiUnavailableError
from ultimatetunes.worker.downloader import Downloader, DownloadError, DownloadProgress

log = logging.getLogger(__name__)

Source = Literal["api", "worker"]
# `canary_runs.message` and the worker's status report stay short.
MAX_MESSAGE = 500
MAX_DETAIL = 200
STAGING_ROOT = "canary"
# The fake catalog's targets (search/fake.py), used with `UT_FAKE_YOUTUBE` (test stack).
FAKE_VIDEO_ID = "Fk2Lp9QwXa1"
FAKE_QUERY = "Lanterns"
FAKE_PLAYLIST_ID = "PLfakeRoadTrip0123456789abcdefGH"


@dataclass(frozen=True)
class Targets:
    """What the canary asks for: the fixed track, a query that finds it, a public playlist."""

    video_id: str
    query: str
    playlist_id: str


def targets(settings: Settings, video_id: str, query: str, playlist_id: str) -> Targets:
    if settings.fake_youtube:
        return Targets(FAKE_VIDEO_ID, FAKE_QUERY, FAKE_PLAYLIST_ID)
    return Targets(video_id, query, playlist_id)


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    duration_ms: int
    detail: str


@dataclass(frozen=True)
class Report:
    source: Source
    # When the run finished (not when it started): see `CatalogCanary.run`.
    ran_at: str
    checks: tuple[Check, ...]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    @property
    def message(self) -> str | None:
        """None when everything passed; else the failed checks, `name: detail; ...`."""
        failed = [f"{c.name}: {c.detail}" for c in self.checks if not c.ok]
        return "; ".join(failed)[:MAX_MESSAGE] if failed else None

    def detail_json(self) -> str:
        """`canary_runs.detail`: one entry per check."""
        return json.dumps(
            [
                {"name": c.name, "ok": c.ok, "durationMs": c.duration_ms, "detail": c.detail}
                for c in self.checks
            ]
        )

    def as_status(self) -> dict[str, object]:
        """The `canary` object of the worker's status report (internal-worker.yaml)."""
        return {"at": self.ran_at, "ok": self.ok, "message": self.message}


class UnexpectedAnswerError(Exception):
    """A check got an answer, but not the expected one (e.g. an empty search)."""


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise UnexpectedAnswerError(message)


def _clip(text: str) -> str:
    return " ".join(text.split())[:MAX_DETAIL]


async def run_check(
    name: str, clock: Clock, timeout_s: float, work: Callable[[], Awaitable[str]]
) -> Check:
    """Runs one check; any failure is a failed `Check`, never an exception."""
    started = clock.monotonic()
    ok = False
    try:
        with anyio.fail_after(timeout_s):
            detail = await work()
        ok = True
    except UnexpectedAnswerError as exc:
        detail = str(exc)
    except CatalogParseError as exc:
        detail = f"layout changed: {exc.message}"
    except TunesError as exc:
        detail = exc.message
    except DownloadError as exc:
        detail = f"{exc.code.value}: {exc.message}"
    except TimeoutError:
        detail = f"timed out after {timeout_s:g} s"
    except Exception as exc:  # reporting any breakage is the canary's job
        log.warning("canary check %s crashed", name, exc_info=exc)
        detail = f"unexpected {type(exc).__name__}"
    duration_ms = max(0, round((clock.monotonic() - started) * 1000))
    return Check(name, ok, duration_ms, _clip(detail))


class CatalogCanary:
    """Api side: the catalog calls the app depends on, against the fixed targets."""

    def __init__(
        self, catalog: MusicCatalog, targets: Targets, clock: Clock, timeout_s: float
    ) -> None:
        self._catalog = catalog
        self._targets = targets
        self._clock = clock
        self._timeout_s = timeout_s
        self._album: str | None = None

    async def run(self) -> Report:
        checks = []
        for name, work in (
            ("search", self._search),
            ("radio", self._radio),
            ("album", self._album_page),
            ("playlist", self._playlist),
        ):
            checks.append(await run_check(name, self._clock, self._timeout_s, work))
        # Stamped when the run ends: a notification sweep that ran meanwhile has its cursor
        # before this time, so a failed run is never skipped.
        return Report("api", format_ts(self._clock.now()), tuple(checks))

    async def _search(self) -> str:
        songs = await self._catalog.search_songs(self._targets.query, 10)
        _expect(bool(songs), "no songs found")
        albums = [s.album.browse_id for s in songs if s.album and s.album.browse_id]
        self._album = albums[0] if albums else None
        return f"{len(songs)} songs"

    async def _radio(self) -> str:
        tracks = await self._catalog.radio(self._targets.video_id, 10)
        _expect(len(tracks) >= 2, "the radio has no other song")  # noqa: PLR2004 - seed + one
        return f"{len(tracks)} songs"

    async def _album_page(self) -> str:
        browse_id = self._album
        if browse_id is None:
            found = await self._catalog.search_albums(self._targets.query, 5)
            _expect(bool(found), "no album found")
            browse_id = found[0].browse_id
        album = await self._catalog.album(browse_id)
        _expect(bool(album.tracks), "the album page has no songs")
        return f"{len(album.tracks)} songs"

    async def _playlist(self) -> str:
        playlist = await self._catalog.playlist(self._targets.playlist_id)
        _expect(bool(playlist.tracks), "the playlist has no songs")
        return f"{len(playlist.tracks)} songs"


async def _ignore(_report: DownloadProgress) -> None:
    return None


class DownloadCanary:
    """Worker side: one download of the fixed track into staging, checked, then deleted."""

    def __init__(  # noqa: PLR0913 - the collaborators of one check, all injected
        self,
        downloader: Downloader,
        staging: StagingStore,
        video_id: str,
        clock: Clock,
        timeout_s: float,
        *,
        token: Callable[[], str] = lambda: secrets.token_hex(8),
        cookies: Callable[[], Awaitable[str | None]] | None = None,
    ) -> None:
        self._downloader = downloader
        self._staging = staging
        self._video_id = video_id
        self._clock = clock
        self._timeout_s = timeout_s
        self._token = token
        # The stored YouTube cookies, fetched per run like a job gets them in its claim.
        self._cookies = cookies

    async def run(self) -> Report:
        check = await run_check("download", self._clock, self._timeout_s, self._download)
        # Stamped when the run ends (see `CatalogCanary.run`).
        return Report("worker", format_ts(self._clock.now()), (check,))

    async def _download(self) -> str:
        job_dir = f"{STAGING_ROOT}/{self._token()}"
        cookies = await self._load_cookies()
        try:
            result = await self._downloader.download(
                self._video_id, job_dir, _ignore, cookies=cookies
            )
            _expect(result.size_bytes > 0, "the download is empty")
            _expect(self._staging.exists(result.final_path), "the downloaded file is missing")
            size = self._staging.size(result.final_path)
            _expect(size == result.size_bytes, "the file size does not match")
            return f"format {result.format_id}, {size} bytes"
        finally:
            # Never kept, never archived: the staging directory goes, whatever happened.
            with anyio.CancelScope(shield=True):
                await anyio.to_thread.run_sync(self._remove, job_dir)

    async def _load_cookies(self) -> str | None:
        """The cookies a real job would use; without them (or if the api cannot give them) the
        canary runs as before. Never logs their content."""
        if self._cookies is None:
            return None
        try:
            return await self._cookies()
        except (ApiUnavailableError, TunesError) as exc:
            log.warning("canary: could not get the YouTube cookies (%s); running without", exc)
            return None

    def _remove(self, job_dir: str) -> None:
        try:
            self._staging.delete(job_dir)
        except OSError as exc:
            log.warning("canary: could not delete %s: %s", job_dir, exc.strerror)
