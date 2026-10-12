# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Registration of archived files (contracts/openapi/internal-worker.yaml, `registerTrack` and
`updateReplayGain`; contracts/ids.md, "Materialization and aliasing").

`register` runs in one transaction, holding the job's lease:

- **Same recording**: a `ready` track with the same MusicBrainz recording id answers
  `merged: true`; the decision is stored on the job (`merge_into_track_id`) and applied by
  `complete` (`jobs/archive.py`). Nothing is reserved.
- **Otherwise**: the artist and album are created or reused (MusicBrainz id, else YouTube id,
  else normalized name), the pending track gets its metadata and file columns (still
  `pending`), and `libraryPath` is reserved on the job (`jobs.library_path`, unique). A path
  held by another track or job is `conflict`. A file already at the path is **adopted** when no
  track owns the path and its SHA-256 equals the registered one (this job's own file, moved by
  an attempt that died before `complete`); any other file there is `conflict`.
- The answer carries the album state: when every track of the album is in the library
  (`totalTracks` known and reached), the worker computes album ReplayGain.

Repeating the call is safe: it recomputes the same decision and keeps one reservation per job.
`replay_gain` stores recomputed gains of the job's own track or of a `ready` track of the same
album (the album-gain rewrite), with the new file size.
"""

import hashlib
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from ultimatetunes.core.clock import Clock, format_ts
from ultimatetunes.core.storage import LibraryStore, StagingStore, check_relative
from ultimatetunes.db.database import Database
from ultimatetunes.db.driver import Connection, IntegrityError
from ultimatetunes.errors import Conflict, LeaseLost, NotFound, PathRejected
from ultimatetunes.ids.uuid7 import new_id
from ultimatetunes.search.text import normalize

_LEASED = ("downloading", "tagging")
_CHUNK = 1024 * 1024
Text = Annotated[str, Field(min_length=1, max_length=1000)]
OptText = Annotated[str | None, Field(default=None, max_length=1000)]
RelPath = Annotated[str, Field(min_length=1, max_length=1024)]
Sha = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Id = Annotated[str, Field(min_length=1, max_length=64)]


class _Body(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, frozen=True)


class FileInfo(_Body):
    format: Literal["opus", "m4a"]
    content_type: Text
    size_bytes: int = Field(ge=1)
    duration_ms: int = Field(ge=1)
    bit_rate_kbps: int | None = None
    sample_rate_hz: int | None = None
    channels: int | None = None
    sha256: Sha


class MusicBrainzIds(_Body):
    recording_id: OptText = None
    track_id: OptText = None
    release_id: OptText = None
    release_group_id: OptText = None
    artist_id: OptText = None
    album_artist_id: OptText = None


class YoutubeIds(_Body):
    album_browse_id: OptText = None
    artist_channel_id: OptText = None


class ReplayGainValues(_Body):
    track_gain_db: float
    track_peak: float = Field(ge=0)
    album_gain_db: float | None = None
    album_peak: float | None = Field(default=None, ge=0)


class TrackMetadata(_Body):
    title: Text
    artist: Text
    artist_sort: OptText = None
    album_artist: Text
    album: Text
    track_number: int | None = None
    disc_number: int | None = None
    total_tracks: int | None = None
    total_discs: int | None = None
    year: int | None = None
    genre: OptText = None
    release_type: OptText = None
    isrc: OptText = None
    musicbrainz: MusicBrainzIds = MusicBrainzIds()
    youtube: YoutubeIds = YoutubeIds()
    replay_gain: ReplayGainValues
    needs_review: bool
    match_score: float | None = Field(default=None, ge=0, le=1)
    cover_path: RelPath | None = None


class RegisterBody(_Body):
    job_id: Id
    lease_id: Id
    track_id: Id
    staging_path: RelPath
    library_path: RelPath
    file: FileInfo
    metadata: TrackMetadata


class NewFile(_Body):
    size_bytes: int = Field(ge=1)
    sha256: Sha


class ReplayGainBody(_Body):
    job_id: Id
    lease_id: Id
    replay_gain: ReplayGainValues
    file: NewFile


@dataclass(frozen=True)
class AlbumTrack:
    track_id: str
    library_path: str


@dataclass(frozen=True)
class AlbumState:
    total_tracks: int | None
    complete: bool
    tracks: list[AlbumTrack]


@dataclass(frozen=True)
class Registered:
    track_id: str
    album_id: str
    artist_id: str
    merged: bool
    album: AlbumState | None

    def to_contract(self) -> dict[str, object]:
        album = None
        if self.album is not None:
            album = {
                "totalTracks": self.album.total_tracks,
                "complete": self.album.complete,
                "tracks": [
                    {"trackId": t.track_id, "libraryPath": t.library_path}
                    for t in self.album.tracks
                ],
            }
        return {
            "trackId": self.track_id,
            "albumId": self.album_id,
            "artistId": self.artist_id,
            "merged": self.merged,
            "album": album,
        }


@dataclass(frozen=True)
class _Job:
    id: str
    track_id: str
    staging_dir: str


def file_sha256(store: LibraryStore, rel: str) -> str:
    sha = hashlib.sha256()
    with store.open_read(rel) as reader:
        while chunk := reader.read(_CHUNK):
            sha.update(chunk)
    return sha.hexdigest()


class Registrar:
    def __init__(
        self, db: Database, clock: Clock, library: LibraryStore, staging: StagingStore
    ) -> None:
        self._db = db
        self._clock = clock
        self._library = library
        self._staging = staging

    # ------------------------------------------------------------ helpers

    def _leased(self, conn: Connection, job_id: str, lease_id: str, now: str) -> _Job:
        row = conn.execute(
            "SELECT id, track_id, state, lease_id, lease_expires_at, attempt_seq FROM jobs"
            " WHERE id = ?",
            (job_id,),
        ).fetchone()
        if row is None:
            raise NotFound("No such job")
        expires = row["lease_expires_at"]
        if (
            row["lease_id"] != lease_id
            or row["state"] not in _LEASED
            or expires is None
            or str(expires) <= now
        ):
            raise LeaseLost()
        return _Job(str(row["id"]), str(row["track_id"]), f"{row['id']}/{row['attempt_seq']}")

    def _artist(  # noqa: PLR0913 - the identity of one artist
        self,
        conn: Connection,
        name: str,
        *,
        sort_name: str | None,
        mbid: str | None,
        channel: str | None,
        now: str,
    ) -> str:
        """By MusicBrainz id, else YouTube channel, else normalized name; created if new.
        Missing ids are filled in on a reused row."""
        name_norm = normalize(name)
        row = None
        if mbid:
            row = conn.execute(
                "SELECT id FROM artists WHERE musicbrainz_id = ?", (mbid,)
            ).fetchone()
        if row is None and channel:
            row = conn.execute(
                "SELECT id FROM artists WHERE yt_channel_id = ?", (channel,)
            ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT id FROM artists WHERE name_norm = ?"
                " AND (musicbrainz_id IS NULL OR ? IS NULL OR musicbrainz_id = ?)"
                " ORDER BY id LIMIT 1",
                (name_norm, mbid, mbid),
            ).fetchone()
        if row is None:
            artist_id = new_id(self._clock)
            conn.execute(
                "INSERT INTO artists (id, name, name_norm, sort_name, musicbrainz_id,"
                " yt_channel_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (artist_id, name, name_norm, sort_name, mbid, channel, now, now),
            )
            return artist_id
        artist_id = str(row["id"])
        self._fill(conn, "artists", artist_id, "musicbrainz_id", mbid, now=now)
        self._fill(conn, "artists", artist_id, "yt_channel_id", channel, now=now)
        self._fill(conn, "artists", artist_id, "sort_name", sort_name, now=now)
        return artist_id

    @staticmethod
    def _fill(  # noqa: PLR0913 - one column of one row
        conn: Connection, table: str, row_id: str, column: str, value: object, *, now: str
    ) -> None:
        """Sets `column` only where it is still NULL and the value is free (UNIQUE columns)."""
        if value is None:
            return
        taken = conn.execute(
            f"SELECT 1 FROM {table} WHERE {column} = ? AND id <> ?",  # noqa: S608  # nosec B608
            (value, row_id),
        ).fetchone()
        if taken is None:
            conn.execute(
                f"UPDATE {table} SET {column} = ?, updated_at = ?"  # noqa: S608  # nosec B608
                f" WHERE id = ? AND {column} IS NULL",
                (value, now, row_id),
            )

    def _album(self, conn: Connection, meta: TrackMetadata, artist_id: str, now: str) -> str:
        mb, yt = meta.musicbrainz, meta.youtube
        name_norm = normalize(meta.album)
        row = None
        if mb.release_id:
            row = conn.execute(
                "SELECT id FROM albums WHERE musicbrainz_release_id = ?", (mb.release_id,)
            ).fetchone()
        if row is None and yt.album_browse_id:
            row = conn.execute(
                "SELECT id FROM albums WHERE yt_browse_id = ?", (yt.album_browse_id,)
            ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT id FROM albums WHERE artist_id = ? AND name_norm = ?"
                " AND (musicbrainz_release_id IS NULL OR ? IS NULL OR musicbrainz_release_id = ?)"
                " ORDER BY id LIMIT 1",
                (artist_id, name_norm, mb.release_id, mb.release_id),
            ).fetchone()
        if row is None:
            album_id = new_id(self._clock)
            conn.execute(
                "INSERT INTO albums (id, artist_id, name, name_norm, year, genre, release_type,"
                " total_tracks, total_discs, musicbrainz_release_id,"
                " musicbrainz_release_group_id, yt_browse_id, cover_path, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    album_id,
                    artist_id,
                    meta.album,
                    name_norm,
                    meta.year,
                    meta.genre,
                    meta.release_type,
                    meta.total_tracks,
                    meta.total_discs,
                    mb.release_id,
                    mb.release_group_id,
                    yt.album_browse_id,
                    meta.cover_path,
                    now,
                    now,
                ),
            )
            return album_id
        album_id = str(row["id"])
        for column, value in (
            ("musicbrainz_release_id", mb.release_id),
            ("musicbrainz_release_group_id", mb.release_group_id),
            ("yt_browse_id", yt.album_browse_id),
            ("year", meta.year),
            ("genre", meta.genre),
            ("release_type", meta.release_type),
            ("total_tracks", meta.total_tracks),
            ("total_discs", meta.total_discs),
            ("cover_path", meta.cover_path),
        ):
            self._fill(conn, "albums", album_id, column, value, now=now)
        return album_id

    def _merge_target(
        self, conn: Connection, job: _Job, recording_id: str | None
    ) -> dict[str, str] | None:
        if not recording_id:
            return None
        row = conn.execute(
            "SELECT id, album_id, artist_id FROM tracks WHERE status = 'ready'"
            " AND musicbrainz_recording_id = ? AND id <> ? ORDER BY archived_at, id LIMIT 1",
            (recording_id, job.track_id),
        ).fetchone()
        if row is None:
            return None
        return {
            "track_id": str(row["id"]),
            "album_id": str(row["album_id"] or ""),
            "artist_id": str(row["artist_id"] or ""),
        }

    def _check_path(self, conn: Connection, job: _Job, path: str, sha: str) -> None:
        owner = conn.execute(
            "SELECT id FROM tracks WHERE path = ? AND id <> ?", (path, job.track_id)
        ).fetchone()
        held = conn.execute(
            "SELECT id FROM jobs WHERE library_path = ? AND id <> ?", (path, job.id)
        ).fetchone()
        if owner is not None or held is not None:
            raise Conflict("libraryPath is held by another track")
        # Adoption (SPEC section 11): this job's own file, moved before a crash.
        if self._library.exists(path) and file_sha256(self._library, path) != sha:
            raise Conflict("another file exists at libraryPath")

    @staticmethod
    def _album_state(conn: Connection, album_id: str, job: _Job, path: str) -> AlbumState:
        total = conn.execute("SELECT total_tracks FROM albums WHERE id = ?", (album_id,)).scalar()
        rows = conn.execute(
            "SELECT id, path FROM tracks WHERE album_id = ? AND status = 'ready'"
            " AND path IS NOT NULL AND id <> ? ORDER BY disc_number, track_number, id",
            (album_id, job.track_id),
        ).fetchall()
        tracks = [AlbumTrack(str(r["id"]), str(r["path"])) for r in rows]
        tracks.append(AlbumTrack(job.track_id, path))
        total_tracks = None if total is None else int(str(total))
        complete = total_tracks is not None and len(tracks) >= total_tracks
        return AlbumState(total_tracks, complete, tracks)

    # ------------------------------------------------------------ register

    def register(self, body: RegisterBody) -> Registered:
        library_path = self._library.check(check_relative(body.library_path))
        staging_path = check_relative(body.staging_path)
        now = format_ts(self._clock.now())
        try:
            with self._db.transaction() as conn:
                return self._register(conn, body, library_path, staging_path, now)
        except IntegrityError as exc:
            # A concurrent register took the path between the check and the update.
            raise Conflict("libraryPath is held by another job") from exc

    def _register(
        self,
        conn: Connection,
        body: RegisterBody,
        library_path: str,
        staging_path: str,
        now: str,
    ) -> Registered:
        job = self._leased(conn, body.job_id, body.lease_id, now)
        if body.track_id != job.track_id:
            raise Conflict("trackId is not the job's track")
        if not staging_path.startswith(f"{job.staging_dir}/"):
            raise PathRejected("stagingPath is outside the job's staging directory")
        if not self._staging.exists(staging_path) or (
            self._staging.size(staging_path) != body.file.size_bytes
        ):
            raise Conflict("the staging file is missing or has another size")
        meta = body.metadata
        target = self._merge_target(conn, job, meta.musicbrainz.recording_id)
        if target is not None:
            conn.execute(
                "UPDATE jobs SET merge_into_track_id = ?, library_path = NULL, updated_at = ?"
                " WHERE id = ?",
                (target["track_id"], now, job.id),
            )
            return Registered(
                target["track_id"], target["album_id"], target["artist_id"], True, None
            )
        self._check_path(conn, job, library_path, body.file.sha256)
        album_artist_id = self._artist(
            conn,
            meta.album_artist,
            sort_name=meta.artist_sort if meta.album_artist == meta.artist else None,
            mbid=meta.musicbrainz.album_artist_id,
            channel=meta.youtube.artist_channel_id if meta.album_artist == meta.artist else None,
            now=now,
        )
        artist_id = (
            album_artist_id
            if meta.artist == meta.album_artist
            and meta.musicbrainz.artist_id == meta.musicbrainz.album_artist_id
            else self._artist(
                conn,
                meta.artist,
                sort_name=meta.artist_sort,
                mbid=meta.musicbrainz.artist_id,
                channel=meta.youtube.artist_channel_id,
                now=now,
            )
        )
        album_id = self._album(conn, meta, album_artist_id, now)
        self._update_track(conn, job, body, artist_id=artist_id, album_id=album_id, now=now)
        conn.execute(
            "UPDATE jobs SET library_path = ?, merge_into_track_id = NULL, updated_at = ?"
            " WHERE id = ?",
            (library_path, now, job.id),
        )
        return Registered(
            job.track_id,
            album_id,
            artist_id,
            False,
            self._album_state(conn, album_id, job, library_path),
        )

    @staticmethod
    def _update_track(  # noqa: PLR0913 - the columns of one registration
        conn: Connection,
        job: _Job,
        body: RegisterBody,
        *,
        artist_id: str,
        album_id: str,
        now: str,
    ) -> None:
        meta, file, gain = body.metadata, body.file, body.metadata.replay_gain
        conn.execute(
            "UPDATE tracks SET title = ?, title_norm = ?, artist_id = ?, album_id = ?,"
            " artist_name = ?, album_name = ?, track_number = ?, disc_number = ?, year = ?,"
            " genre = ?, duration_ms = ?, format = ?, content_type = ?, size_bytes = ?,"
            " bit_rate_kbps = ?, sample_rate_hz = ?, channels = ?, rg_track_gain_db = ?,"
            " rg_track_peak = ?, rg_album_gain_db = ?, rg_album_peak = ?, needs_review = ?,"
            " musicbrainz_recording_id = ?, musicbrainz_track_id = ?, isrc = ?,"
            " yt_album_browse_id = COALESCE(?, yt_album_browse_id),"
            " yt_artist_channel_id = COALESCE(?, yt_artist_channel_id), updated_at = ?"
            " WHERE id = ? AND status = 'pending'",
            (
                meta.title,
                normalize(meta.title),
                artist_id,
                album_id,
                meta.artist,
                meta.album,
                meta.track_number,
                meta.disc_number,
                meta.year,
                meta.genre,
                file.duration_ms,
                file.format,
                file.content_type,
                file.size_bytes,
                file.bit_rate_kbps,
                file.sample_rate_hz,
                file.channels,
                gain.track_gain_db,
                gain.track_peak,
                gain.album_gain_db,
                gain.album_peak,
                1 if meta.needs_review else 0,
                meta.musicbrainz.recording_id,
                meta.musicbrainz.track_id,
                meta.isrc,
                meta.youtube.album_browse_id,
                meta.youtube.artist_channel_id,
                now,
                job.track_id,
            ),
        )

    # ------------------------------------------------------------ replay gain

    def replay_gain(self, track_id: str, body: ReplayGainBody) -> None:
        now = format_ts(self._clock.now())
        with self._db.transaction() as conn:
            job = self._leased(conn, body.job_id, body.lease_id, now)
            row = conn.execute(
                "SELECT t.id, t.status, t.path, t.album_id,"
                " (SELECT album_id FROM tracks WHERE id = ?) AS job_album"
                " FROM tracks t WHERE t.id = ?",
                (job.track_id, track_id),
            ).fetchone()
            if row is None:
                raise NotFound("No such track")
            own = track_id == job.track_id
            same_album = row["album_id"] is not None and row["album_id"] == row["job_album"]
            if not own and not (row["status"] == "ready" and same_album):
                raise Conflict("the track is not part of this job's album")
            if not own and self._library.size(str(row["path"])) != body.file.size_bytes:
                raise Conflict("the library file has another size")
            gain = body.replay_gain
            conn.execute(
                "UPDATE tracks SET rg_track_gain_db = ?, rg_track_peak = ?,"
                " rg_album_gain_db = ?, rg_album_peak = ?, size_bytes = ?, updated_at = ?"
                " WHERE id = ?",
                (
                    gain.track_gain_db,
                    gain.track_peak,
                    gain.album_gain_db,
                    gain.album_peak,
                    body.file.size_bytes,
                    now,
                    track_id,
                ),
            )
