# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`POST /ut/v1/tracks/{id}/request` and `GET /ut/v1/tracks/{id}/status` (RF-04), against
the contract's `TrackStatus` schema, with the fake catalog. No network."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import anyio
import pytest
from fastapi.testclient import TestClient

from tests.library.harness import schema
from tests.streaming.harness import ANA, KEYS, Keys
from ultimatetunes.app import create_app
from ultimatetunes.core.clock import FakeClock, format_ts
from ultimatetunes.core.services import Services, build_services
from ultimatetunes.db import Database
from ultimatetunes.errors import NotFound
from ultimatetunes.jobs import tracks
from ultimatetunes.jobs.queue import PRIORITY_KEEP, PRIORITY_PREFETCH, ProgressReport
from ultimatetunes.settings import Settings

VIDEO = "Rb8Tn3ZcYv0"
SONG = f"yt:{VIDEO}"
HEADERS = {"X-Api-Key": "utk_ana"}
STATUS = schema("ut-v1.yaml", "TrackStatus")


class Api:
    def __init__(self, client: TestClient, services: Services, clock: FakeClock) -> None:
        self.client = client
        self.services = services
        self.clock = clock

    def request(self, song: str, body: Any = None, **kwargs: Any) -> Any:
        r = self.client.post(f"/ut/v1/tracks/{song}/request", headers=HEADERS, json=body, **kwargs)
        if r.status_code in (200, 202):
            STATUS.validate(r.json())
        return r

    def status(self, song: str) -> Any:
        r = self.client.get(f"/ut/v1/tracks/{song}/status", headers=HEADERS)
        if r.status_code == 200:
            STATUS.validate(r.json())
        return r

    def sql(self, statement: str, params: tuple[object, ...] = ()) -> Any:
        with self.services.db.transaction() as conn:
            return conn.execute(statement, params).scalar()


@pytest.fixture
def api(
    settings: Settings,
    db: Database,
    clock: FakeClock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Api]:
    monkeypatch.setenv("UT_LIBRARY_SCAN_ON_START", "false")
    monkeypatch.setenv("UT_STAGING_SWEEP_INTERVAL_S", "0")
    monkeypatch.setenv("UT_CANARY_ENABLED", "false")
    from ultimatetunes.library.web import library_settings  # noqa: PLC0415

    library_settings.cache_clear()
    configured = settings.model_copy(update={"database_path": tmp_path / "data" / "ut.db"})
    services = build_services(configured, clock)
    services.authenticator = Keys()
    now = format_ts(clock.now())
    with services.db.transaction() as conn:
        for user in KEYS.values():
            conn.execute(
                "INSERT INTO users (id, username, password_hash, role, created_at, updated_at)"
                " VALUES (?, ?, 'x', 'user', ?, ?)",
                (user.user_id, user.username, now, now),
            )
    with TestClient(create_app(services=services)) as client:
        yield Api(client, services, clock)
    library_settings.cache_clear()


def test_an_external_song_nobody_asked_for(api: Api) -> None:
    body = api.status(SONG).json()
    assert body == {
        "id": SONG,
        "trackId": None,
        "state": "not_requested",
        "progress": 0,
        "attempts": 0,
        "maxAttempts": 3,
        "error": None,
        "streamable": False,
        "updatedAt": None,
    }
    assert api.sql("SELECT COUNT(*) FROM tracks") == 0


def test_a_request_materializes_and_queues_in_one_go(api: Api) -> None:
    r = api.request(SONG)
    assert r.status_code == 202
    body = r.json()
    assert body["state"] == "queued"
    assert body["trackId"] is not None
    assert body["updatedAt"] is not None
    assert api.sql("SELECT priority FROM jobs") == PRIORITY_KEEP
    assert api.sql("SELECT requested_by FROM jobs") == ANA.user_id
    assert api.sql("SELECT alias FROM track_aliases") == SONG
    # Asking again (also by its library id) joins the same job; prefetch raises the priority.
    again = api.request(body["trackId"], {"reason": "prefetch"})
    assert again.status_code == 202
    assert api.sql("SELECT COUNT(*) FROM jobs") == 1
    assert api.sql("SELECT priority FROM jobs") == PRIORITY_PREFETCH
    assert api.status(body["trackId"]).json()["trackId"] == body["trackId"]


def test_status_follows_the_download(api: Api) -> None:
    track_id = api.request(SONG).json()["trackId"]
    claimed = api.services.jobs.claim("w1", lease_s=60)
    assert claimed is not None
    body = api.status(SONG).json()
    assert (body["state"], body["attempts"], body["streamable"]) == ("downloading", 1, False)
    base = claimed.job.staging_dir
    api.services.jobs.progress(
        claimed.job.id,
        claimed.lease.lease_id,
        ProgressReport(
            state="downloading",
            progress=0.42,
            bytes_downloaded=420,
            expected_size=1000,
            part_path=f"{base}/{VIDEO}.webm.part",
            final_path=f"{base}/{VIDEO}.webm",
            finished=False,
            format_id="251",
            content_type="audio/webm",
            progressive=True,
        ),
    )
    body = api.status(track_id).json()
    assert (body["state"], body["progress"], body["streamable"]) == ("downloading", 0.42, True)
    api.services.jobs.fail(
        claimed.job.id,
        claimed.lease.lease_id,
        error_code="network_error",
        retryable=True,
        message="timed out",
    )
    body = api.status(SONG).json()
    assert body["state"] == "queued"
    assert body["error"] == {"code": "network_error", "message": "timed out"}


def test_a_failed_track_is_queued_again(api: Api) -> None:
    api.request(SONG)
    claimed = api.services.jobs.claim("w1", lease_s=60)
    assert claimed is not None
    api.services.jobs.fail(
        claimed.job.id,
        claimed.lease.lease_id,
        error_code="video_unavailable",
        retryable=False,
        message="",
    )
    body = api.status(SONG).json()
    assert body["state"] == "failed"
    assert body["error"] == {"code": "video_unavailable", "message": "video_unavailable"}
    r = api.request(SONG)
    assert r.status_code == 202
    assert (r.json()["state"], r.json()["attempts"], r.json()["error"]) == ("queued", 0, None)


def test_a_ready_track_queues_nothing(api: Api) -> None:
    now = format_ts(api.clock.now())
    track_id = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01c0bb"
    api.sql(
        "INSERT INTO tracks (id, status, title, title_norm, artist_name, path, created_at,"
        " updated_at) VALUES (?, 'ready', 'T', 't', 'A', 'A/T.opus', ?, ?)",
        (track_id, now, now),
    )
    r = api.request(track_id)
    assert r.status_code == 200
    body = r.json()
    assert (body["state"], body["progress"], body["streamable"]) == ("ready", 1, True)
    assert body["updatedAt"] == now
    assert api.sql("SELECT COUNT(*) FROM jobs") == 0
    # Once a download job completes, its status is the job's.
    api.request(SONG)
    api.sql("UPDATE jobs SET state = 'ready', progress = 0.9")
    api.sql("UPDATE tracks SET status = 'ready' WHERE yt_video_id = ?", (VIDEO,))
    body = api.status(SONG).json()
    assert (body["state"], body["progress"], body["streamable"]) == ("ready", 1, True)


def test_a_pending_track_without_a_job_or_a_video(api: Api) -> None:
    now = format_ts(api.clock.now())
    track_id = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01c0cc"
    api.sql(
        "INSERT INTO tracks (id, status, title, title_norm, artist_name, created_at, updated_at)"
        " VALUES (?, 'pending', 'T', 't', 'A', ?, ?)",
        (track_id, now, now),
    )
    body = api.status(track_id).json()
    assert (body["state"], body["trackId"]) == ("not_requested", track_id)
    r = api.request(track_id)
    assert r.status_code == 404
    assert r.json()["code"] == "not_found"


def test_bad_requests(api: Api) -> None:
    assert api.request("yt:Zz9Zz9Zz9Zz").status_code == 404  # not in the catalog
    assert api.status("0199d6a2-4c1e-7b3a-9f10-2a6c8e01c0dd").status_code == 404
    assert api.status("ytalbum:MPREb_abc").status_code == 400
    assert api.request(SONG, {"reason": "hoard"}).status_code == 400
    big = api.client.post(f"/ut/v1/tracks/{SONG}/request", headers=HEADERS, content=b" " * 5000)
    assert big.status_code == 400
    assert api.client.post(f"/ut/v1/tracks/{SONG}/request").status_code == 401
    assert api.sql("SELECT COUNT(*) FROM jobs") == 0


def test_a_virtual_id_needs_its_catalog_record(api: Api) -> None:
    with pytest.raises(NotFound):
        tracks.request_in(api.services, SONG, None, reason="keep", user_id=ANA.user_id)


def test_a_track_archived_after_the_catalog_lookup_answers_ready(api: Api) -> None:
    record = anyio.run(api.services.catalog.track, VIDEO)  # looked up while SONG had no track
    now = format_ts(api.clock.now())
    track_id = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01c0ee"
    api.sql(
        "INSERT INTO tracks (id, status, title, title_norm, artist_name, path, yt_video_id,"
        " created_at, updated_at) VALUES (?, 'ready', 'T', 't', 'A', 'A/T.opus', ?, ?, ?)",
        (track_id, VIDEO, now, now),
    )
    queued, found = tracks.request_in(
        api.services, SONG, record, reason="keep", user_id=ANA.user_id
    )
    assert not queued
    assert (found.state, found.track_id) == ("ready", track_id)
    assert api.sql("SELECT COUNT(*) FROM jobs") == 0


def test_a_track_removed_meanwhile_is_not_found(api: Api) -> None:
    with pytest.raises(NotFound):
        tracks.request_in(
            api.services,
            "0199d6a2-4c1e-7b3a-9f10-2a6c8e01c0ff",
            None,
            reason="keep",
            user_id=ANA.user_id,
        )


def test_status_needs_an_api_key(api: Api) -> None:
    r = api.client.get(f"/ut/v1/tracks/{SONG}/status")
    assert r.status_code == 401
    assert (
        api.client.get(
            f"/ut/v1/tracks/{SONG}/status", headers={"X-Api-Key": "utk_nobody"}
        ).status_code
        == 401
    )
