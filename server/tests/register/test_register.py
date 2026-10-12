# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`registerTrack` and `updateReplayGain` against the real api (in process): reservation,
merge, conflicts and adoption, album state, artist/album reuse, ReplayGain updates."""

import hashlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from tests.jobs.test_queue import add_track, to_tagging
from tests.library.harness import Keys
from ultimatetunes.app import create_app
from ultimatetunes.core.clock import FakeClock, format_ts
from ultimatetunes.core.services import Services, build_services
from ultimatetunes.db import Database
from ultimatetunes.db.driver import IntegrityError
from ultimatetunes.jobs.queue import Claimed, SqliteJobQueue
from ultimatetunes.library.register import Registrar
from ultimatetunes.settings import Settings

pytestmark = pytest.mark.anyio
TOKEN = "worker-token-for-tests"
VIDEO = "Rb8Tn3ZcYv0"
PATH = "The Paper Lanterns/Lanterns at Dusk/04 - Paper Moons (Live).opus"
RECORDING = "2b4d6f8a-1c3e-4a5b-9d7f-0e2c4a6b8d01"
RELEASE = "4d6f8a0c-3e5a-4b7c-8f9a-1b3d5f7a9c02"
ARTIST_MB = "5f0c2d6e-8b1a-4c3d-9e7f-1a2b3c4d5e01"
AUDIO = b"OggS" + b"\x01" * 100


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _Row(dict[str, Any]):
    """A row by column name, or by position (and slices) like a tuple."""

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, (int, slice)):
            return tuple(self.values())[key]
        return super().__getitem__(key)


@dataclass
class Api:
    services: Services
    db: Database
    clock: FakeClock
    client: httpx.AsyncClient

    def row(self, sql: str, *params: object) -> Any:
        with self.db.read() as conn:
            found = conn.execute(sql, params).fetchone()
        assert found is not None
        return _Row(found)

    def count(self, table: str) -> int:
        with self.db.read() as conn:
            return int(str(conn.execute(f"SELECT COUNT(*) FROM {table}").scalar()))  # noqa: S608

    async def register(self, body: dict[str, Any]) -> httpx.Response:
        return await self.client.post(
            "/internal/v1/library/tracks",
            json=body,
            headers={"Authorization": f"Bearer {TOKEN}"},
        )

    async def replay_gain(self, track_id: str, body: dict[str, Any]) -> httpx.Response:
        return await self.client.put(
            f"/internal/v1/library/tracks/{track_id}/replaygain",
            json=body,
            headers={"Authorization": f"Bearer {TOKEN}"},
        )


@pytest.fixture
async def api(
    settings: Settings, db: Database, clock: FakeClock, tmp_path: Path
) -> AsyncIterator[Api]:
    configured = settings.model_copy(
        update={"worker_token": SecretStr(TOKEN), "database_path": tmp_path / "data" / "ut.db"}
    )
    services = build_services(configured, clock)
    services.authenticator = Keys()  # `apiKey=utk_ana` on /rest (tests/library/harness.py)
    transport = httpx.ASGITransport(app=create_app(services=services))
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as client:
        yield Api(services, db, clock, client)
    services.db.close()


@dataclass(frozen=True)
class Claim:
    job_id: str
    lease_id: str
    track_id: str
    staging_dir: str
    claimed: Claimed


def claim(api: Api, track_id: str = "t1", video: str = VIDEO, audio: bytes = AUDIO) -> Claim:
    add_track(api.db, api.clock, track_id, video)
    api.services.jobs.enqueue(track_id=track_id, video_id=video, priority=100)
    claimed = api.services.jobs.claim("w1", lease_s=60)
    assert claimed is not None
    job = claimed.job
    with api.services.staging.open_write(f"{job.staging_dir}/archive.opus") as out:
        out.write(audio)
    return Claim(job.id, claimed.lease.lease_id, track_id, job.staging_dir, claimed)


def body(c: Claim, path: str = PATH, audio: bytes = AUDIO, **meta: Any) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "title": "Paper Moons (Live)",
        "artist": "The Paper Lanterns",
        "artistSort": "Paper Lanterns, The",
        "albumArtist": "The Paper Lanterns",
        "album": "Lanterns at Dusk",
        "trackNumber": 4,
        "discNumber": 1,
        "totalTracks": 9,
        "totalDiscs": 1,
        "year": 2024,
        "genre": "Indie Pop",
        "releaseType": "live",
        "isrc": None,
        "musicbrainz": {
            "recordingId": RECORDING,
            "trackId": None,
            "releaseId": RELEASE,
            "releaseGroupId": None,
            "artistId": ARTIST_MB,
            "albumArtistId": ARTIST_MB,
        },
        "youtube": {"albumBrowseId": "MPREb_k3Vd9QmT2xL", "artistChannelId": "UCq8Xb"},
        "replayGain": {"trackGainDb": -7.85, "trackPeak": 0.993},
        "needsReview": False,
        "matchScore": 0.94,
        "coverPath": "The Paper Lanterns/Lanterns at Dusk/cover.jpg",
    }
    metadata.update(meta)
    return {
        "jobId": c.job_id,
        "leaseId": c.lease_id,
        "trackId": c.track_id,
        "stagingPath": f"{c.staging_dir}/archive.opus",
        "libraryPath": path,
        "file": {
            "format": "opus",
            "contentType": "audio/ogg",
            "sizeBytes": len(audio),
            "durationMs": 262040,
            "bitRateKbps": 131,
            "sampleRateHz": 48000,
            "channels": 2,
            "sha256": hashlib.sha256(audio).hexdigest(),
        },
        "metadata": metadata,
    }


def ready_track(  # noqa: PLR0913 - the columns a test needs
    api: Api,
    track_id: str,
    *,
    path: str,
    album_id: str | None = None,
    recording: str | None = None,
    audio: bytes = b"other",
) -> None:
    now = format_ts(api.clock.now())
    with api.services.library.open_write(path) as out:
        out.write(audio)
    with api.db.transaction() as conn:
        conn.execute(
            "INSERT INTO tracks (id, status, title, title_norm, artist_name, path, album_id,"
            " musicbrainz_recording_id, size_bytes, created_at, updated_at, archived_at)"
            " VALUES (?, 'ready', 'Other', 'other', 'X', ?, ?, ?, ?, ?, ?, ?)",
            (track_id, path, album_id, recording, len(audio), now, now, now),
        )


async def test_register_reserves_the_path_and_fills_the_track(api: Api) -> None:
    c = claim(api)
    r = await api.register(body(c))
    assert r.status_code == 200, r.text
    found = r.json()
    assert (found["trackId"], found["merged"]) == ("t1", False)
    assert found["album"] == {
        "totalTracks": 9,
        "complete": False,
        "tracks": [{"trackId": "t1", "libraryPath": PATH}],
    }
    track = api.row("SELECT * FROM tracks WHERE id = 't1'")
    assert (track["status"], track["title"], track["album_name"]) == (
        "pending",
        "Paper Moons (Live)",
        "Lanterns at Dusk",
    )
    assert (track["size_bytes"], track["format"], track["rg_track_gain_db"]) == (
        len(AUDIO),
        "opus",
        -7.85,
    )
    assert (track["artist_id"], track["album_id"]) == (found["artistId"], found["albumId"])
    assert track["musicbrainz_recording_id"] == RECORDING
    assert api.row("SELECT library_path FROM jobs WHERE id = ?", c.job_id)[0] == PATH
    album = api.row("SELECT * FROM albums WHERE id = ?", found["albumId"])
    assert (album["musicbrainz_release_id"], album["total_tracks"], album["cover_path"]) == (
        RELEASE,
        9,
        "The Paper Lanterns/Lanterns at Dusk/cover.jpg",
    )
    artist = api.row("SELECT * FROM artists WHERE id = ?", found["artistId"])
    assert (artist["musicbrainz_id"], artist["sort_name"], artist["yt_channel_id"]) == (
        ARTIST_MB,
        "Paper Lanterns, The",
        "UCq8Xb",
    )
    # Idempotent: the same answer, no second artist or album.
    again = await api.register(body(c))
    assert again.json() == found
    assert (api.count("artists"), api.count("albums")) == (1, 1)
    # A retry with another path replaces the reservation.
    other = PATH.replace("04 - ", "")
    assert (await api.register(body(c, other))).status_code == 200
    assert api.row("SELECT library_path FROM jobs WHERE id = ?", c.job_id)[0] == other


async def test_the_whole_archive_flow_through_complete(api: Api) -> None:
    c = claim(api)
    assert (await api.register(body(c))).status_code == 200
    assert isinstance(api.services.jobs, SqliteJobQueue)
    to_tagging(api.services.jobs, c.claimed)
    api.services.library.import_file(api.services.staging, f"{c.staging_dir}/archive.opus", PATH)
    done = await api.client.post(
        f"/internal/v1/jobs/{c.job_id}/complete",
        json={
            "leaseId": c.lease_id,
            "trackId": "t1",
            "libraryPath": PATH,
            "staging": {"path": f"{c.staging_dir}/archive.opus", "sizeBytes": len(AUDIO)},
        },
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert done.status_code == 200, done.text
    assert api.row("SELECT status, path FROM tracks WHERE id = 't1'")[:] == ("ready", PATH)


async def test_the_same_recording_is_merged(api: Api) -> None:
    ready_track(api, "t0", path="A/B/01 - Old.opus", recording=RECORDING)
    c = claim(api)
    r = await api.register(body(c))
    assert r.json() == {
        "trackId": "t0",
        "albumId": None,
        "artistId": None,
        "merged": True,
        "album": None,
    }
    job = api.row("SELECT library_path, merge_into_track_id FROM jobs WHERE id = ?", c.job_id)
    assert (job[0], job[1]) == (None, "t0")


async def test_paths_held_elsewhere_are_conflicts(api: Api) -> None:
    ready_track(api, "t0", path=PATH)
    c = claim(api)
    r = await api.register(body(c, musicbrainz={}))
    assert (r.status_code, r.json()["code"]) == (409, "conflict")
    c2 = claim(api, "t2", "Qx7Lm2pZ0aB")
    other = "A/B/02 - X.opus"
    # Another job's reservation.
    with api.db.transaction() as conn:
        conn.execute("UPDATE jobs SET library_path = ? WHERE id = ?", (other, c2.job_id))
    assert (await api.register(body(c, other, musicbrainz={}))).status_code == 409


async def test_an_existing_file_is_adopted_only_when_it_is_the_same(api: Api) -> None:
    c = claim(api)
    with api.services.library.open_write(PATH) as out:
        out.write(AUDIO)  # moved by an attempt that died before complete
    assert (await api.register(body(c))).status_code == 200
    with api.services.library.open_write(PATH) as out:
        out.write(b"someone else's file")
    r = await api.register(body(c))
    assert (r.status_code, r.json()["code"]) == (409, "conflict")


async def test_a_complete_album_lists_its_tracks(api: Api) -> None:
    c = claim(api)
    first = (await api.register(body(c, totalTracks=2))).json()
    ready_track(api, "t0", path="The Paper Lanterns/Lanterns at Dusk/01 - A.opus")
    with api.db.transaction() as conn:
        conn.execute("UPDATE tracks SET album_id = ? WHERE id = 't0'", (first["albumId"],))
    album = (await api.register(body(c, totalTracks=2))).json()["album"]
    assert album["complete"] is True
    assert [t["trackId"] for t in album["tracks"]] == ["t0", "t1"]


@pytest.mark.parametrize(
    ("change", "status", "code"),
    [
        ({"leaseId": "stale"}, 409, "lease_lost"),
        ({"jobId": "missing"}, 404, "not_found"),
        ({"trackId": "t9"}, 409, "conflict"),
        ({"libraryPath": "../outside.opus"}, 422, "path_rejected"),
        ({"stagingPath": "elsewhere/archive.opus"}, 422, "path_rejected"),
        ({"file": {"format": "flac"}}, 400, "invalid_parameter"),
    ],
)
async def test_bad_registrations(api: Api, change: dict[str, Any], status: int, code: str) -> None:
    c = claim(api)
    r = await api.register(body(c) | change)
    assert (r.status_code, r.json()["code"]) == (status, code)


async def test_the_staging_file_must_match(api: Api) -> None:
    c = claim(api)
    r = await api.register(body(c, audio=AUDIO + b"x"))
    assert (r.status_code, r.json()["code"]) == (409, "conflict")


async def test_artists_and_albums_are_reused(api: Api) -> None:
    c = claim(api)
    first = (await api.register(body(c))).json()
    c2 = claim(api, "t2", "Qx7Lm2pZ0aB", audio=b"two")
    # Same channel and album browse id, no MusicBrainz ids, another artist spelling.
    second = (
        await api.register(
            body(
                c2,
                "The Paper Lanterns/Lanterns at Dusk/05 - B.opus",
                audio=b"two",
                artist="The Paper Lanterns",
                musicbrainz={},
            )
        )
    ).json()
    assert (second["artistId"], second["albumId"]) == (first["artistId"], first["albumId"])
    c3 = claim(api, "t3", "Zz1Lm2pZ0aB", audio=b"three")
    third = (
        await api.register(
            body(
                c3,
                "Guest/Lanterns at Dusk/06 - C.opus",
                audio=b"three",
                artist="Guest Singer",
                musicbrainz={"albumArtistId": ARTIST_MB, "releaseId": RELEASE},
                youtube={},
            )
        )
    ).json()
    assert third["albumId"] == first["albumId"]
    assert third["artistId"] != first["artistId"]
    by_name = api.row("SELECT COUNT(*) FROM artists WHERE name_norm = 'guest singer'")[0]
    assert by_name == 1


async def test_replay_gain_updates(api: Api) -> None:
    c = claim(api)
    registered = (await api.register(body(c, totalTracks=2))).json()
    other = "The Paper Lanterns/Lanterns at Dusk/01 - A.opus"
    ready_track(api, "t0", path=other, album_id=registered["albumId"], audio=b"retagged!")
    ready_track(api, "tx", path="X/Y/01 - Z.opus")
    gain = {"trackGainDb": -1.0, "trackPeak": 0.5, "albumGainDb": -2.0, "albumPeak": 0.9}

    def put(size: int, **extra: Any) -> dict[str, Any]:
        return {
            "jobId": c.job_id,
            "leaseId": c.lease_id,
            "replayGain": gain,
            "file": {"sizeBytes": size, "sha256": "0" * 64},
        } | extra

    assert (await api.replay_gain("t1", put(150))).status_code == 204
    assert api.row("SELECT size_bytes, rg_album_gain_db FROM tracks WHERE id = 't1'")[:] == (
        150,
        -2.0,
    )
    assert (await api.replay_gain("t0", put(9))).status_code == 204
    assert api.row("SELECT rg_album_peak FROM tracks WHERE id = 't0'")[0] == 0.9
    assert (await api.replay_gain("t0", put(10))).status_code == 409  # not the file's size
    assert (await api.replay_gain("tx", put(5))).status_code == 409  # another album
    assert (await api.replay_gain("nope", put(5))).status_code == 404
    assert (await api.replay_gain("x" * 65, put(5))).status_code == 400
    assert (await api.replay_gain("t1", put(5, leaseId="stale"))).status_code == 409
    bad = await api.replay_gain("t1", {"jobId": c.job_id})
    assert bad.status_code == 400


def release(api: Api, c: Claim) -> Claim:
    """The attempt dies (retryable failure), the backoff passes, the job is claimed again."""
    api.services.jobs.fail(
        c.job_id, c.lease_id, error_code="storage_error", retryable=True, message="died"
    )
    api.clock.advance(3600)
    claimed = api.services.jobs.claim("w2", lease_s=60)
    assert claimed is not None
    with api.services.staging.open_write(f"{claimed.job.staging_dir}/archive.opus") as out:
        out.write(AUDIO)
    return Claim(c.job_id, claimed.lease.lease_id, c.track_id, claimed.job.staging_dir, claimed)


async def test_the_album_gain_version_of_a_moved_file_is_adopted(api: Api) -> None:
    """Last track of an album: register, album gain rewrites the file (reported with the
    ReplayGain PUT), the file is moved, the attempt dies before complete. The retry registers
    the pre-gain hash again and the api adopts the moved file anyway."""
    c = claim(api)
    assert (await api.register(body(c))).status_code == 200
    rewritten = AUDIO + b"album gain tags"
    gain = {"trackGainDb": -1.0, "trackPeak": 0.5, "albumGainDb": -2.0, "albumPeak": 0.9}
    sha = hashlib.sha256(rewritten).hexdigest()
    put = {
        "jobId": c.job_id,
        "leaseId": c.lease_id,
        "replayGain": gain,
        "file": {"sizeBytes": len(rewritten), "sha256": sha},
    }
    assert (await api.replay_gain("t1", put)).status_code == 204
    with api.services.library.open_write(PATH) as out:
        out.write(rewritten)  # moved, then the worker died
    again = release(api, c)
    r = await api.register(body(again))
    assert r.status_code == 200, r.text
    job = api.row(
        "SELECT library_path, placed_path, placed_sha256 FROM jobs WHERE id = ?", c.job_id
    )
    assert job[:] == (PATH, PATH, sha)
    assert api.services.library.exists(PATH)


async def test_a_retry_that_merges_removes_the_file_it_had_moved(api: Api) -> None:
    c = claim(api)
    assert (await api.register(body(c))).status_code == 200
    with api.services.library.open_write(PATH) as out:
        out.write(AUDIO)
    again = release(api, c)
    # Meanwhile the same recording became ready elsewhere.
    ready_track(api, "t0", path="A/B/01 - Old.opus", recording=RECORDING)
    r = await api.register(body(again))
    assert r.json()["merged"] is True
    assert not api.services.library.exists(PATH)
    job = api.row("SELECT placed_path, merge_into_track_id FROM jobs WHERE id = ?", c.job_id)
    assert job[:] == (None, "t0")


async def test_a_retry_with_another_path_removes_the_old_file(api: Api) -> None:
    c = claim(api)
    assert (await api.register(body(c))).status_code == 200
    with api.services.library.open_write(PATH) as out:
        out.write(AUDIO)
    again = release(api, c)
    other = PATH.replace("04 - ", "")
    assert (await api.register(body(again, other))).status_code == 200
    assert not api.services.library.exists(PATH)


@pytest.mark.parametrize("change", ["owned", "held", "different", "missing", "unreadable"])
async def test_a_placed_file_is_only_removed_when_it_is_still_ours(api: Api, change: str) -> None:
    c = claim(api)
    assert (await api.register(body(c))).status_code == 200
    if change != "missing":
        with api.services.library.open_write(PATH) as out:
            out.write(AUDIO if change != "different" else b"changed")
    again = release(api, c)
    if change == "owned":
        with api.db.transaction() as conn:
            conn.execute("UPDATE tracks SET path = ? WHERE id = 't1'", (PATH,))
    if change == "held":
        c2 = claim(api, "t2", "Qx7Lm2pZ0aB")
        with api.db.transaction() as conn:
            conn.execute("UPDATE jobs SET library_path = ? WHERE id = ?", (PATH, c2.job_id))
    if change == "unreadable":
        api.services.library.delete(PATH)
        (api.services.library.local_path(PATH)).mkdir(parents=True)
    other = PATH.replace("04 - ", "")
    assert (await api.register(body(again, other))).status_code == 200
    assert api.services.library.exists(PATH) is (change != "missing")


async def test_a_directory_at_the_path_is_a_conflict(api: Api) -> None:
    c = claim(api)
    api.services.library.local_path(PATH).mkdir(parents=True)
    r = await api.register(body(c))
    assert (r.status_code, r.json()["code"]) == (409, "conflict")


async def test_concurrent_artist_and_album_creation_is_found_again(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = claim(api)
    first = (await api.register(body(c))).json()
    # Another register created both rows between our lookup and our insert: the first
    # lookups miss them, the inserts are skipped, the second lookups find them.
    for name in ("_find_artist", "_find_album"):
        real = getattr(Registrar, name)
        misses = {"left": 1}

        def once(*args: Any, _real: Any = real, _misses: dict[str, int] = misses) -> Any:
            if _misses["left"]:
                _misses["left"] -= 1
                return None
            return _real(*args)

        monkeypatch.setattr(Registrar, name, staticmethod(once))
    c2 = claim(api, "t2", "Qx7Lm2pZ0aB", audio=b"two")
    second = (
        await api.register(body(c2, "The Paper Lanterns/Lanterns at Dusk/x.opus", audio=b"two"))
    ).json()
    assert (second["artistId"], second["albumId"]) == (first["artistId"], first["albumId"])
    assert (api.count("artists"), api.count("albums")) == (1, 1)


@pytest.mark.parametrize("finder", ["_find_artist", "_find_album"])
async def test_rows_that_cannot_be_created_or_found_are_conflicts(
    api: Api, monkeypatch: pytest.MonkeyPatch, finder: str
) -> None:
    c = claim(api)
    await api.register(body(c))
    monkeypatch.setattr(Registrar, finder, staticmethod(lambda *_args: None))
    c2 = claim(api, "t2", "Qx7Lm2pZ0aB", audio=b"two")
    r = await api.register(body(c2, "The Paper Lanterns/Lanterns at Dusk/x.opus", audio=b"two"))
    assert (r.status_code, r.json()["code"]) == (409, "conflict")


@pytest.mark.parametrize(("failures", "status"), [(1, 200), (2, 409)])
async def test_a_unique_race_is_retried_once(
    api: Api, monkeypatch: pytest.MonkeyPatch, failures: int, status: int
) -> None:
    real = Registrar._register
    left = {"n": failures}

    def racing(self: Registrar, *args: Any) -> Any:
        if left["n"]:
            left["n"] -= 1
            raise IntegrityError("UNIQUE constraint failed: jobs.library_path")
        return real(self, *args)

    monkeypatch.setattr(Registrar, "_register", racing)
    c = claim(api)
    assert (await api.register(body(c))).status_code == status


async def test_replay_gain_of_a_missing_library_file_is_not_found(api: Api) -> None:
    c = claim(api)
    registered = (await api.register(body(c, totalTracks=2))).json()
    ready_track(api, "t0", path="A/B/01 - A.opus", album_id=registered["albumId"])
    api.services.library.delete("A/B/01 - A.opus")
    put = {
        "jobId": c.job_id,
        "leaseId": c.lease_id,
        "replayGain": {"trackGainDb": -1.0, "trackPeak": 0.5},
        "file": {"sizeBytes": 5, "sha256": "0" * 64},
    }
    r = await api.replay_gain("t0", put)
    assert (r.status_code, r.json()["code"]) == (404, "not_found")
