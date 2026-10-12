# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`TaggingArchiver`: the worker's `Archiver` (PLAN T09, contracts/openapi/internal-worker.yaml).

Runs inside the worker loop's shielded scope, still holding the lease:

1. **Build** the archive file in the attempt's staging directory: probe, remux by stream copy
   (Opus to `.opus`, AAC to `.m4a` with faststart; never transcoded, SPEC section 11), track
   ReplayGain, metadata (YouTube Music completed with MusicBrainz when the match is strong,
   else `needs_review`), cover (Cover Art Archive, else the YouTube thumbnail), tags.
2. **Register** it (`registerTrack`) with the sanitized `Artist/Album/NN - Title.ext` path. A
   path another track holds (`conflict`) is retried once with the video id as a suffix.
   `merged: true`: the recording is already in the library; nothing goes into `/music`.
3. **Album gain**: when register says the album is complete, album ReplayGain is measured over
   all its files, their tags are rewritten (library files through a temporary file and a
   rename, this job's file in staging) and reported with `PUT .../replaygain`. Best effort: a
   failure there is logged and the track keeps its track gain.
4. **Move** the file into `/music` at the reserved path (`LibraryStore.import_file`: atomic,
   never overwrites), then the cover next to it unless one is there already.

The loop then calls `complete`. Failures are `DownloadError`s: `tagging_failed` (ffmpeg,
mutagen, an unsupported codec), `storage_error` (the library path cannot be used).
"""

import hashlib
import logging
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

import anyio
import httpx

from ultimatetunes.core.clock import Clock, SystemClock
from ultimatetunes.core.ratelimit import RateLimiter
from ultimatetunes.core.storage import FileStore, LibraryStore, StagingStore
from ultimatetunes.errors import Conflict, PathRejected, WorkerErrorCode
from ultimatetunes.paths import cover_path, library_path
from ultimatetunes.settings import Settings
from ultimatetunes.tagging.covers import CoverFetcher
from ultimatetunes.tagging.ffmpeg import Ffmpeg, FfmpegError
from ultimatetunes.tagging.matching import Query, YoutubeIds
from ultimatetunes.tagging.model import (
    KIND_BY_EXT,
    ArchiveKind,
    FileInfo,
    ReplayGain,
    TrackMetadata,
)
from ultimatetunes.tagging.musicbrainz import MetadataResolver, MusicBrainz
from ultimatetunes.tagging.ratelimit import MemoryRateLimiter
from ultimatetunes.tagging.settings import TaggingSettings
from ultimatetunes.tagging.tags import TaggingError, read_track_gain, write_replay_gain, write_tags
from ultimatetunes.worker.archiver import Archived, ArchiveRequest
from ultimatetunes.worker.client import ClaimedJob
from ultimatetunes.worker.downloader import DownloadError

log = logging.getLogger(__name__)

ClientFactory = Callable[[], httpx.AsyncClient]
_CHUNK = 1024 * 1024


@dataclass(frozen=True)
class Digest:
    size_bytes: int
    sha256: str


def digest(store: FileStore, rel: str) -> Digest:
    sha = hashlib.sha256()
    size = 0
    with store.open_read(rel) as reader:
        while chunk := reader.read(_CHUNK):
            sha.update(chunk)
            size += len(chunk)
    return Digest(size, sha.hexdigest())


@dataclass
class _Built:
    """The archive file in staging and what register needs."""

    rel: str
    kind: ArchiveKind
    info: FileInfo
    meta: TrackMetadata
    gain: ReplayGain
    cover_rel: str | None
    staged_cover: str | None


@dataclass(frozen=True)
class _AlbumFile:
    track_id: str
    store: FileStore
    rel: str
    kind: ArchiveKind
    mine: bool


class TaggingArchiver:
    def __init__(  # noqa: PLR0913 - collaborators, all injectable for tests
        self,
        settings: TaggingSettings,
        *,
        lookups: bool = True,
        ffmpeg: Ffmpeg | None = None,
        limiter: RateLimiter | None = None,
        clock: Clock | None = None,
        client_factory: ClientFactory | None = None,
        sleep: Callable[[float], Awaitable[None]] = anyio.sleep,
    ) -> None:
        self.settings = settings
        self.lookups = lookups
        self.ffmpeg = ffmpeg or Ffmpeg(settings)
        self.limiter = limiter or MemoryRateLimiter(clock or SystemClock())
        self.client_factory = client_factory or self._default_client
        self.sleep = sleep

    def _default_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self.settings.metadata_timeout_s, follow_redirects=False)

    async def archive(self, request: ArchiveRequest) -> Archived:
        try:
            return await self._archive(request)
        except (FfmpegError, TaggingError) as exc:
            raise DownloadError(WorkerErrorCode.TAGGING_FAILED, str(exc)) from exc
        except PathRejected as exc:
            raise DownloadError(
                WorkerErrorCode.TAGGING_FAILED, f"path rejected: {exc.message}", retryable=False
            ) from exc

    async def _archive(self, request: ArchiveRequest) -> Archived:
        built = await self.build(request)
        lib_rel, registered = await self._register(request, built)
        track_id = str(registered["trackId"])
        if registered.get("merged"):
            log.info("job %s: same recording as track %s, merged", request.job.job_id, track_id)
            return Archived(track_id, None)
        album = registered.get("album")
        if isinstance(album, dict) and album.get("complete"):
            await self._album_gain(request, built, album)
        sha = (await anyio.to_thread.run_sync(digest, request.staging, built.rel)).sha256
        await anyio.to_thread.run_sync(self._place, request, built.rel, lib_rel, sha)
        if built.staged_cover is not None and built.cover_rel is not None:
            await anyio.to_thread.run_sync(
                self._place_cover, request, built.staged_cover, built.cover_rel
            )
        return Archived(track_id, lib_rel)

    # ------------------------------------------------------------ 1. build

    async def build(self, request: ArchiveRequest) -> _Built:
        job, staging = request.job, request.staging
        source = staging.local_path(request.download.final_path)
        probe = await self.ffmpeg.probe(source)
        kind = probe.kind()
        if kind is None:
            raise DownloadError(
                WorkerErrorCode.TAGGING_FAILED,
                f"unsupported audio codec {probe.codec[:32]!r}",
                retryable=False,
            )
        rel = f"{job.staging_dir}/archive.{kind.ext}"
        staging.delete(rel)
        await self.ffmpeg.remux(source, staging.local_path(rel), kind)
        path = staging.local_path(rel)
        archived = await self.ffmpeg.probe(path)
        duration_ms = archived.duration_ms or probe.duration_ms or request.download.duration_ms
        if not duration_ms or duration_ms < 1:
            raise DownloadError(WorkerErrorCode.TAGGING_FAILED, "the audio has no duration")
        loudness = await self.ffmpeg.loudness([path])
        gain = ReplayGain(loudness.gain_db, loudness.true_peak)
        query = Query(job.hints.title, job.hints.artist, job.hints.album, duration_ms)
        hints = YoutubeIds(
            album_browse_id=job.hints.album_browse_id,
            artist_channel_id=job.hints.artist_channel_id,
            track_number=job.hints.track_number,
            year=job.hints.year,
        )
        async with self.client_factory() as client:
            meta = await self._resolver(client).resolve(query, hints)
            cover_rel, staged_cover = await self._cover(client, request, meta)
        await anyio.to_thread.run_sync(write_tags, path, kind, meta, gain)
        file = await anyio.to_thread.run_sync(digest, staging, rel)
        info = FileInfo(
            kind=kind,
            size_bytes=file.size_bytes,
            duration_ms=duration_ms,
            sha256=file.sha256,
            bit_rate_kbps=archived.bit_rate_kbps or probe.bit_rate_kbps,
            sample_rate_hz=archived.sample_rate_hz,
            channels=archived.channels,
        )
        return _Built(rel, kind, info, meta, gain, cover_rel, staged_cover)

    def _resolver(self, client: httpx.AsyncClient) -> MetadataResolver:
        enabled = self.lookups and self.settings.musicbrainz_enabled
        musicbrainz = MusicBrainz(client, self.limiter, sleep=self.sleep) if enabled else None
        return MetadataResolver(musicbrainz, self.settings.musicbrainz_min_score)

    async def _cover(
        self, client: httpx.AsyncClient, request: ArchiveRequest, meta: TrackMetadata
    ) -> tuple[str | None, str | None]:
        """(`coverPath` to register, staged cover to move) — the library's cover is kept."""
        rel = cover_path(meta.album_artist, meta.album)
        if request.library.exists(rel):
            return rel, None
        if not (self.lookups and self.settings.covers_enabled):
            return None, None
        data = await CoverFetcher(client).fetch(
            release_id=meta.musicbrainz.release_id,
            release_group_id=meta.musicbrainz.release_group_id,
            thumbnail_url=request.job.hints.thumbnail_url,
        )
        if data is None:
            return None, None
        staged = f"{request.job.staging_dir}/cover.jpg"
        with request.staging.open_write(staged) as out:
            out.write(data)
        return rel, staged

    # ------------------------------------------------------------ 2. register

    def _body(self, job: ClaimedJob, built: _Built, lib_rel: str) -> dict[str, Any]:
        return {
            "jobId": job.job_id,
            "leaseId": job.lease_id,
            "trackId": job.track_id,
            "stagingPath": built.rel,
            "libraryPath": lib_rel,
            "file": built.info.to_contract(),
            "metadata": built.meta.to_contract(built.gain, built.cover_rel),
        }

    def _path(self, built: _Built, suffix: str | None = None) -> str:
        meta = built.meta
        return library_path(
            artist=meta.album_artist,
            album=meta.album,
            title=meta.title,
            ext=built.kind.ext,
            track_number=meta.track_number,
            disc_number=meta.disc_number,
            suffix=suffix,
        )

    async def _register(self, request: ArchiveRequest, built: _Built) -> tuple[str, dict[str, Any]]:
        job, api = request.job, request.api
        lib_rel = request.library.check(self._path(built))
        try:
            return lib_rel, await api.register_track(self._body(job, built, lib_rel))
        except Conflict:
            log.info("job %s: %s is taken, adding the video id", job.job_id, lib_rel)
        lib_rel = request.library.check(self._path(built, suffix=job.video_id))
        try:
            return lib_rel, await api.register_track(self._body(job, built, lib_rel))
        except Conflict as exc:
            raise DownloadError(
                WorkerErrorCode.STORAGE_ERROR, "no free library path", retryable=False
            ) from exc

    # ------------------------------------------------------------ 3. album gain

    async def _album_gain(
        self, request: ArchiveRequest, built: _Built, album: dict[str, Any]
    ) -> None:
        try:
            files = self._album_files(request, built, album)
            if files is None:
                return
            paths = [f.store.local_path(f.rel) for f in files]
            loudness = await self.ffmpeg.loudness(paths)
            for file in files:
                track = built.gain if file.mine else await self._track_gain(file)
                gain = ReplayGain(
                    track.track_gain_db, track.track_peak, loudness.gain_db, loudness.true_peak
                )
                new = await anyio.to_thread.run_sync(self._retag, file, gain)
                await request.api.update_replay_gain(
                    file.track_id,
                    {
                        "jobId": request.job.job_id,
                        "leaseId": request.job.lease_id,
                        "replayGain": gain.to_contract(),
                        "file": {"sizeBytes": new.size_bytes, "sha256": new.sha256},
                    },
                )
        except (FfmpegError, TaggingError, PathRejected, OSError) as exc:
            log.warning("job %s: album ReplayGain skipped: %s", request.job.job_id, exc)

    def _album_files(
        self, request: ArchiveRequest, built: _Built, album: dict[str, Any]
    ) -> list[_AlbumFile] | None:
        files: list[_AlbumFile] = []
        tracks = album.get("tracks")
        for entry in tracks if isinstance(tracks, list) else []:
            track_id, rel = str(entry.get("trackId")), str(entry.get("libraryPath"))
            if track_id == request.job.track_id:
                files.append(_AlbumFile(track_id, request.staging, built.rel, built.kind, True))
                continue
            kind = KIND_BY_EXT.get(PurePosixPath(rel).suffix.lstrip("."))
            if kind is None or not request.library.exists(rel):
                log.warning("job %s: album track %s is not usable", request.job.job_id, track_id)
                return None
            files.append(_AlbumFile(track_id, request.library, rel, kind, False))
        return files if any(f.mine for f in files) else None

    async def _track_gain(self, file: _AlbumFile) -> ReplayGain:
        path = file.store.local_path(file.rel)
        stored = await anyio.to_thread.run_sync(read_track_gain, path, file.kind)
        if stored is not None:
            return stored
        loudness = await self.ffmpeg.loudness([path])
        return ReplayGain(loudness.gain_db, loudness.true_peak)

    @staticmethod
    def _retag(file: _AlbumFile, gain: ReplayGain) -> Digest:
        """This job's file in place (staging); a library file through a temporary copy and an
        atomic rename, so a reader never sees a half-written file."""
        if file.mine:
            write_replay_gain(file.store.local_path(file.rel), file.kind, gain)
            return digest(file.store, file.rel)
        path = PurePosixPath(file.rel)
        tmp = str(path.parent / f".{path.name}.{secrets.token_hex(4)}.tmp")
        try:
            with file.store.open_read(file.rel) as reader, file.store.open_write(tmp) as writer:
                while chunk := reader.read(_CHUNK):
                    writer.write(chunk)
            write_replay_gain(file.store.local_path(tmp), file.kind, gain)
            file.store.rename(tmp, file.rel)
        finally:
            file.store.delete(tmp)
        return digest(file.store, file.rel)

    # ------------------------------------------------------------ 4. move

    @staticmethod
    def _place(request: ArchiveRequest, rel: str, lib_rel: str, sha: str) -> None:
        library: LibraryStore = request.library
        staging: StagingStore = request.staging
        try:
            library.import_file(staging, rel, lib_rel)
        except Conflict as exc:
            # A retry after a crash between the move and `complete`: our own file is fine.
            if digest(library, lib_rel).sha256 != sha:
                raise DownloadError(
                    WorkerErrorCode.STORAGE_ERROR,
                    "another file is at the reserved library path",
                    retryable=False,
                ) from exc

    @staticmethod
    def _place_cover(request: ArchiveRequest, staged: str, rel: str) -> None:
        try:
            request.library.import_file(request.staging, staged, rel)
        except Conflict:
            log.info("cover %s already exists, kept", rel)


def build_archiver(settings: Settings) -> TaggingArchiver:
    """The worker's archiver. The test stack (`UT_FAKE_YOUTUBE`) never contacts MusicBrainz,
    Cover Art Archive or YouTube: tracks keep the catalog data and are marked `needs_review`."""
    return TaggingArchiver(TaggingSettings(), lookups=not settings.fake_youtube)
