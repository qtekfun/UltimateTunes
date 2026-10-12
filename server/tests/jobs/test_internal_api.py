# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The jobs side of the internal worker API over HTTP (contracts/openapi/internal-worker.yaml)."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from tests.jobs.test_queue import add_track
from ultimatetunes.app import create_app
from ultimatetunes.core.clock import FakeClock
from ultimatetunes.core.services import Services, build_services
from ultimatetunes.db import Database
from ultimatetunes.settings import Settings

TOKEN = "worker-token-for-tests-0123456789abcdef"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
VIDEO = "Rb8Tn3ZcYv0"


@pytest.fixture
def services(settings: Settings, db: Database, clock: FakeClock, tmp_path: Path) -> Services:
    configured = settings.model_copy(
        update={"worker_token": SecretStr(TOKEN), "database_path": tmp_path / "data" / "ut.db"}
    )
    return build_services(configured, clock)


@pytest.fixture
def client(services: Services) -> Iterator[TestClient]:
    with TestClient(create_app(services=services)) as test_client:
        yield test_client


@pytest.fixture
def job_id(services: Services, db: Database, clock: FakeClock) -> str:
    add_track(db, clock, "t1", VIDEO)
    with db.transaction() as conn:
        conn.execute(
            "UPDATE tracks SET album_name = 'Lanterns at Dusk', duration_ms = 262000,"
            " yt_thumbnail_url = 'https://i.ytimg.com/vi/x/hqdefault.jpg' WHERE id = 't1'"
        )
    return services.jobs.enqueue(track_id="t1", video_id=VIDEO, priority=100).id


def claim(client: TestClient) -> dict[str, Any]:
    r = client.post(
        "/internal/v1/jobs/claim", json={"workerId": "w1", "leaseSeconds": 30}, headers=AUTH
    )
    assert r.status_code == 200
    body: dict[str, Any] = r.json()
    return body


def progress_body(lease: str, staging_dir: str, **changes: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "leaseId": lease,
        "state": "downloading",
        "progress": 0.25,
        "bytesDownloaded": 10,
        "expectedSize": 40,
        "partPath": f"{staging_dir}/{VIDEO}.webm.part",
        "finalPath": f"{staging_dir}/{VIDEO}.webm",
        "finished": False,
        "formatId": "251",
        "contentType": "audio/webm",
        "progressive": True,
    }
    body.update(changes)
    return body


def test_claim_answers_204_with_retry_after_when_idle(client: TestClient) -> None:
    r = client.post("/internal/v1/jobs/claim", json={"workerId": "w1"}, headers=AUTH)
    assert r.status_code == 204
    assert r.headers["retry-after"] == "2"
    r = client.post("/internal/v1/jobs/claim", json={"workerId": "w1", "kinds": []}, headers=AUTH)
    assert r.status_code == 204


def test_claim_returns_the_job_hints_and_lease(client: TestClient, job_id: str) -> None:
    body = claim(client)
    assert body["job"] == {
        "id": job_id,
        "kind": "download",
        "trackId": "t1",
        "videoId": VIDEO,
        "attempt": 1,
        "maxAttempts": 3,
        "priority": 100,
        "stagingDir": f"{job_id}/1",
        "hints": {
            "title": "Glass Orchard",
            "artist": "The Paper Lanterns",
            "album": "Lanterns at Dusk",
            "albumBrowseId": None,
            "artistChannelId": None,
            "durationMs": 262000,
            "year": None,
            "trackNumber": None,
            "thumbnailUrl": "https://i.ytimg.com/vi/x/hqdefault.jpg",
        },
    }
    assert body["lease"]["heartbeatSeconds"] == 10
    assert body["lease"]["expiresAt"] == "2026-10-12T08:00:30.000Z"


def test_heartbeat_progress_and_fail(client: TestClient, job_id: str, clock: FakeClock) -> None:
    body = claim(client)
    lease, staging_dir = body["lease"]["leaseId"], body["job"]["stagingDir"]
    clock.advance(5)
    r = client.post(f"/internal/v1/jobs/{job_id}/heartbeat", json={"leaseId": lease}, headers=AUTH)
    assert r.json() == {
        "leaseId": lease,
        "expiresAt": "2026-10-12T08:01:05.000Z",
        "cancelRequested": False,
    }
    r = client.post(
        f"/internal/v1/jobs/{job_id}/progress", json=progress_body(lease, staging_dir), headers=AUTH
    )
    assert r.status_code == 200
    assert r.json()["cancelRequested"] is False
    r = client.post(
        f"/internal/v1/jobs/{job_id}/progress",
        json=progress_body(lease, staging_dir, partPath="elsewhere/x.part"),
        headers=AUTH,
    )
    assert (r.status_code, r.json()["code"]) == (422, "path_rejected")
    r = client.post(
        f"/internal/v1/jobs/{job_id}/progress",
        json=progress_body(lease, staging_dir, expectedSize=41),
        headers=AUTH,
    )
    assert (r.status_code, r.json()["code"]) == (409, "invalid_state_transition")
    fail = {"leaseId": lease, "errorCode": "network_error", "retryable": True, "message": "slow"}
    r = client.post(f"/internal/v1/jobs/{job_id}/fail", json=fail, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["state"] == "queued"
    assert r.json()["attempts"] == 1
    assert r.json()["notBefore"] is not None
    again = client.post(f"/internal/v1/jobs/{job_id}/fail", json=fail, headers=AUTH)
    assert again.json() == r.json()
    r = client.post(f"/internal/v1/jobs/{job_id}/heartbeat", json={"leaseId": lease}, headers=AUTH)
    assert (r.status_code, r.json()["code"]) == (409, "lease_lost")
    r = client.post("/internal/v1/jobs/nope/heartbeat", json={"leaseId": lease}, headers=AUTH)
    assert (r.status_code, r.json()["code"]) == (404, "not_found")


def test_complete_after_registration(
    client: TestClient, job_id: str, db: Database, services: Services
) -> None:
    body = claim(client)
    lease, staging_dir = body["lease"]["leaseId"], body["job"]["stagingDir"]
    tagging = progress_body(
        lease, staging_dir, state="tagging", finished=True, bytesDownloaded=40, progress=1
    )
    assert (
        client.post(f"/internal/v1/jobs/{job_id}/progress", json=tagging, headers=AUTH).status_code
        == 200
    )
    path = "The Paper Lanterns/Lanterns at Dusk/04 - Glass Orchard.opus"
    complete = {
        "leaseId": lease,
        "trackId": "t1",
        "libraryPath": path,
        "staging": {"path": f"{staging_dir}/{VIDEO}.webm", "sizeBytes": 40, "sha256": None},
    }
    r = client.post(f"/internal/v1/jobs/{job_id}/complete", json=complete, headers=AUTH)
    assert (r.status_code, r.json()["code"]) == (409, "invalid_state_transition")
    with db.transaction() as conn:
        conn.execute("UPDATE tracks SET size_bytes = 3 WHERE id = 't1'")
        conn.execute("UPDATE jobs SET library_path = ? WHERE id = ?", (path, job_id))
    with services.library.open_write(path) as out:
        out.write(b"abc")
    r = client.post(f"/internal/v1/jobs/{job_id}/complete", json=complete, headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"jobId": job_id, "state": "ready", "attempts": 1, "notBefore": None}
    with db.read() as conn:
        assert conn.execute("SELECT status FROM tracks WHERE id = 't1'").scalar() == "ready"


def test_bodies_are_validated(client: TestClient, job_id: str) -> None:
    body = claim(client)
    lease = body["lease"]["leaseId"]
    bad_code = {"leaseId": lease, "errorCode": "lease_expired", "retryable": True, "message": ""}
    r = client.post(f"/internal/v1/jobs/{job_id}/fail", json=bad_code, headers=AUTH)
    assert (r.status_code, r.json()["code"]) == (400, "invalid_parameter")
    r = client.post(
        "/internal/v1/jobs/claim", json={"workerId": "w", "leaseSeconds": 5}, headers=AUTH
    )
    assert r.status_code == 400


def test_worker_status_returns_pending_commands(client: TestClient, db: Database) -> None:
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO worker_commands (id, command, created_at)"
            " VALUES ('c1', 'update_ytdlp', '2026-10-12T07:00:00.000Z')"
        )
    status = {
        "version": "0.1.0",
        "ytdlpVersion": "2026.08.19",
        "canary": {"at": "2026-10-12T03:00:12.000Z", "ok": True, "message": None},
    }
    r = client.put("/internal/v1/workers/w1/status", json=status, headers=AUTH)
    assert r.json() == {"commands": ["update_ytdlp"]}
    r = client.put("/internal/v1/workers/w1/status", json=status | {"canary": None}, headers=AUTH)
    assert r.json() == {"commands": []}


def test_a_lost_app_state_falls_back_to_default_settings(client: TestClient) -> None:
    del client.app.state.jobs_settings  # type: ignore[attr-defined]
    r = client.post("/internal/v1/jobs/claim", json={"workerId": "w1"}, headers=AUTH)
    assert r.headers["retry-after"] == "2"


def test_the_token_is_checked_before_the_body(client: TestClient) -> None:
    r = client.post("/internal/v1/jobs/claim", content=b"{not json")
    assert (r.status_code, r.json()["code"]) == (401, "invalid_worker_token")
    r = client.post("/internal/v1/jobs/claim", content=b"{not json", headers=AUTH)
    assert (r.status_code, r.json()["code"]) == (400, "invalid_parameter")
    r = client.post("/internal/v1/jobs/claim", headers=AUTH)
    assert r.status_code == 400
    assert r.json()["detail"] == "Invalid: body"


def test_absurd_ids_are_refused(client: TestClient) -> None:
    r = client.post(f"/internal/v1/jobs/{'j' * 65}/heartbeat", json={"leaseId": "l"}, headers=AUTH)
    assert r.json()["detail"] == "Invalid: jobId"
    status = {"version": "v", "ytdlpVersion": "y"}
    r = client.put(f"/internal/v1/workers/{'w' * 101}/status", json=status, headers=AUTH)
    assert r.json()["detail"] == "Invalid: workerId"
