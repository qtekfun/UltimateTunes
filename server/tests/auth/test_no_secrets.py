# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""No API key, password or password hash ever reaches a log record, an audit entry or an error
(CLAUDE.md, Security). Our records are checked raw, before the redacting filter, so the auth code
itself never emits a secret; every record is checked once more through the redacting pipeline."""

import json
import logging
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from tests.auth.conftest import ADMIN_PASSWORD
from tests.auth.test_routes import auth_services
from ultimatetunes.app import create_app
from ultimatetunes.auth.service import AuthService
from ultimatetunes.core.clock import FakeClock
from ultimatetunes.logging import JsonFormatter, RedactingFilter
from ultimatetunes.settings import Settings

WRONG_PASSWORD = "a wrong but secret guess"


class Collect(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def records() -> Iterator[list[logging.LogRecord]]:
    handler = Collect()
    root = logging.getLogger()
    previous = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    yield handler.records
    root.removeHandler(handler)
    root.setLevel(previous)


def test_no_secret_in_logs_audit_or_errors(
    migrated_settings: Settings, clock: FakeClock, records: list[logging.LogRecord]
) -> None:
    services = auth_services(migrated_settings, clock)
    responses: list[str] = []
    with TestClient(create_app(services=services), raise_server_exceptions=False) as c:
        service = c.app.state.auth  # type: ignore[attr-defined]
        assert isinstance(service, AuthService)
        service.bootstrap_admin("alice", ADMIN_PASSWORD)
        body = {"username": "alice", "password": ADMIN_PASSWORD, "name": "Phone"}
        created = c.post("/ut/v1/keys", json=body)
        key = created.json()["secret"]
        key_id = created.json()["key"]["id"]
        calls = [
            c.get("/ut/v1/me", headers={"X-Api-Key": key}),
            c.get("/ut/v1/keys", params={"apiKey": key}),
            c.post("/ut/v1/keys", json={**body, "password": WRONG_PASSWORD}),
            c.post("/ut/v1/keys", json={**body, "password": WRONG_PASSWORD}),  # delays alice
            c.post("/ut/v1/keys", json=body),
            c.get("/rest/ping", params={"u": "alice", "p": ADMIN_PASSWORD, "f": "json"}),
            c.get("/rest/ping", params={"u": "alice", "p": "enc:" + key.encode().hex()}),
            c.get("/rest/ping", params={"apiKey": key, "u": "alice"}),
            c.get("/rest/ping", params={"apiKey": key[:-1] + "x"}),
            c.delete(f"/ut/v1/keys/{key_id}", headers={"X-Api-Key": key}),
            c.get("/ut/v1/me", headers={"X-Api-Key": key}),
        ]
        responses = [r.text for r in calls]
        users = service.list_users()
        audit = service.recent_audit()
    password_hash = users[0].password_hash
    secrets = [key, key[:-1] + "x", ADMIN_PASSWORD, WRONG_PASSWORD, password_hash]
    secrets.append(key.encode().hex())

    formatter = JsonFormatter()
    redacting = RedactingFilter()
    ours = [r for r in records if r.name.startswith("ultimatetunes")]
    assert any(r.name == "ultimatetunes.auth.service" for r in ours)
    for record in ours:
        raw = record.getMessage()
        for secret in secrets:
            assert secret not in raw, record.msg
    # Every record (the test client's own request log included) once through the log pipeline.
    for record in records:
        redacting.filter(record)
        line = formatter.format(record)
        for secret in secrets:
            assert secret not in line
    actions = {entry.action for entry in audit}
    assert {"user.create", "key.create", "key.revoke"} <= actions
    audit_text = json.dumps([entry.__dict__ for entry in audit])
    for text in [audit_text, *responses]:
        for secret in secrets:
            assert secret not in text
