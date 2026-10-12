# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`/ut/v1/me`, `/ut/v1/keys` and authentication through the real app and `/rest` pipeline."""

from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from tests.auth.conftest import ADMIN_PASSWORD, USER_PASSWORD, fast_passwords
from ultimatetunes.app import create_app
from ultimatetunes.auth import web
from ultimatetunes.auth.routes import CreateKeyRequest
from ultimatetunes.auth.service import HELP_URL, AuthService
from ultimatetunes.auth.settings import AuthSettings
from ultimatetunes.core.clock import FakeClock
from ultimatetunes.core.services import Services, build_services
from ultimatetunes.settings import Settings
from ultimatetunes.subsonic.router import SubsonicRequest, SubsonicRouter, build_rest_router

UNKNOWN_KEY = "utk_EXAMPLEexampleEXAMPLEexampleEXAMPLEexampleE"


def auth_services(settings: Settings, clock: FakeClock) -> Services:
    services = build_services(settings, clock)
    services.authenticator = AuthService(
        services.db,
        clock,
        services.rate_limiter,
        AuthSettings(auth_lockout_s=60, auth_max_failures_per_user=2),
        fast_passwords(),
    )
    return services


@pytest.fixture
def services(migrated_settings: Settings, clock: FakeClock) -> Iterator[Services]:
    services = auth_services(migrated_settings, clock)
    yield services
    services.db.close()


@pytest.fixture
def client(services: Services) -> Iterator[TestClient]:
    with TestClient(create_app(services=services)) as test_client:
        yield test_client


@pytest.fixture
def auth(client: TestClient) -> AuthService:
    service = client.app.state.auth  # type: ignore[attr-defined]
    assert isinstance(service, AuthService)
    service.create_user("alice", ADMIN_PASSWORD, "admin", actor=None)
    service.create_user("bob", USER_PASSWORD, "user", actor=None)
    return service


def new_key(client: TestClient, username: str, password: str, name: str = "Pixel 9") -> str:
    r = client.post("/ut/v1/keys", json={"username": username, "password": password, "name": name})
    assert r.status_code == 201, r.text
    secret: str = r.json()["secret"]
    return secret


def problem(r: object, status: int, code: str) -> Mapping[str, object]:
    assert getattr(r, "status_code", None) == status
    body: Mapping[str, object] = r.json()  # type: ignore[attr-defined]
    assert body["code"] == code
    return body


# ---------------------------------------------------------------- POST /ut/v1/keys


def test_create_key(client: TestClient, auth: AuthService) -> None:
    r = client.post(
        "/ut/v1/keys",
        json={"username": "Alice", "password": ADMIN_PASSWORD, "name": "Pixel 9", "extra": 1},
    )
    assert r.status_code == 201
    assert r.headers["cache-control"] == "no-store"
    body = r.json()
    secret = body["secret"]
    assert secret.startswith("utk_")
    assert len(secret) == 47
    key = body["key"]
    assert key["name"] == "Pixel 9"
    assert key["prefix"] == secret[:12]
    assert key["lastUsedAt"] is None
    assert key["revokedAt"] is None
    assert key["current"] is False
    assert set(key) == {"id", "name", "prefix", "createdAt", "lastUsedAt", "revokedAt", "current"}
    me = client.get("/ut/v1/me", headers={"X-Api-Key": secret})
    assert me.json() == {
        "id": auth.list_users()[0].id,
        "username": "alice",
        "role": "admin",
        "apiKeyId": key["id"],
    }


def test_create_key_wrong_password_or_user(client: TestClient, auth: AuthService) -> None:
    wrong = client.post("/ut/v1/keys", json={"username": "alice", "password": "nope", "name": "x"})
    unknown = client.post("/ut/v1/keys", json={"username": "zed", "password": "nope", "name": "x"})
    a = problem(wrong, 401, "authentication_failed")
    b = problem(unknown, 401, "authentication_failed")
    assert a["detail"] == b["detail"]


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"[]",
        b'{"username": "alice", "password": "x"}',
        b'{"username": "", "password": "x", "name": "n"}',
        b'{"username": 1, "password": "x", "name": "n"}',
        b'{"username": "alice", "password": "x", "name": "' + b"n" * 101 + b'"}',
    ],
)
def test_create_key_invalid_body(client: TestClient, auth: AuthService, body: bytes) -> None:
    r = client.post("/ut/v1/keys", content=body, headers={"content-type": "application/json"})
    problem(r, 400, "invalid_parameter")


def test_create_key_body_too_large(client: TestClient, auth: AuthService) -> None:
    big = b'{"username": "' + b"a" * 20000 + b'"}'
    r = client.post("/ut/v1/keys", content=big, headers={"content-type": "application/json"})
    problem(r, 413, "payload_too_large")

    def chunks() -> Iterator[bytes]:
        for _ in range(20):
            yield b" " * 1024

    r = client.post("/ut/v1/keys", content=chunks(), headers={"content-type": "application/json"})
    problem(r, 413, "payload_too_large")


def test_create_key_with_a_key_of_another_user(client: TestClient, auth: AuthService) -> None:
    bob = new_key(client, "bob", USER_PASSWORD)
    body = {"username": "alice", "password": ADMIN_PASSWORD, "name": "Laptop"}
    r = client.post("/ut/v1/keys", json=body, headers={"X-Api-Key": bob})
    problem(r, 400, "conflicting_auth")
    alice = new_key(client, "alice", ADMIN_PASSWORD)
    assert client.post("/ut/v1/keys", json=body, headers={"X-Api-Key": alice}).status_code == 201
    assert client.post("/ut/v1/keys", json=body, params={"apiKey": alice}).status_code == 201
    r = client.post("/ut/v1/keys", json=body, headers={"X-Api-Key": UNKNOWN_KEY})
    problem(r, 401, "invalid_api_key")


def test_create_key_lockout_answers_429(client: TestClient, auth: AuthService) -> None:
    body = {"username": "alice", "password": "guess", "name": "x"}
    for _ in range(2):
        problem(client.post("/ut/v1/keys", json=body), 401, "authentication_failed")
    body["password"] = ADMIN_PASSWORD
    r = client.post("/ut/v1/keys", json=body)
    problem(r, 429, "rate_limited")
    assert r.headers["retry-after"] == "60"


def test_create_key_request_hides_the_password() -> None:
    body = CreateKeyRequest.model_validate_json(
        '{"username": "alice", "password": "a secret passphrase", "name": "x"}'
    )
    assert body.password.get_secret_value() == "a secret passphrase"
    assert "a secret passphrase" not in repr(body)
    assert "a secret passphrase" not in str(body)


# ---------------------------------------------------------------- authenticated routes


def test_me_needs_a_valid_key(client: TestClient, auth: AuthService) -> None:
    problem(client.get("/ut/v1/me"), 401, "authentication_required")
    problem(client.get("/ut/v1/me", headers={"X-Api-Key": UNKNOWN_KEY}), 401, "invalid_api_key")
    key = new_key(client, "bob", USER_PASSWORD)
    r = client.get("/ut/v1/me", params={"apiKey": key})
    assert r.status_code == 200
    assert r.json()["role"] == "user"
    r = client.get("/ut/v1/me", params={"apiKey": key}, headers={"X-Api-Key": UNKNOWN_KEY})
    problem(r, 400, "conflicting_auth")


def test_list_and_revoke_keys(client: TestClient, auth: AuthService, clock: FakeClock) -> None:
    first = new_key(client, "alice", ADMIN_PASSWORD, "Phone")
    clock.advance(1)
    second = new_key(client, "alice", ADMIN_PASSWORD, "Tablet")
    bob = new_key(client, "bob", USER_PASSWORD)
    r = client.get("/ut/v1/keys", headers={"X-Api-Key": first})
    assert r.status_code == 200
    listed = r.json()["keys"]
    assert [(k["name"], k["current"]) for k in listed] == [("Tablet", False), ("Phone", True)]
    assert listed[1]["lastUsedAt"] is not None
    tablet_id = listed[0]["id"]
    bob_id = client.get("/ut/v1/keys", headers={"X-Api-Key": bob}).json()["keys"][0]["id"]

    # Someone else's key does not exist for this user.
    problem(client.delete(f"/ut/v1/keys/{bob_id}", headers={"X-Api-Key": first}), 404, "not_found")
    for _ in range(2):  # idempotent
        r = client.delete(f"/ut/v1/keys/{tablet_id}", headers={"X-Api-Key": first})
        assert r.status_code == 204
        assert r.content == b""
    problem(client.get("/ut/v1/me", headers={"X-Api-Key": second}), 401, "invalid_api_key")
    listed = client.get("/ut/v1/keys", headers={"X-Api-Key": first}).json()["keys"]
    assert listed[0]["revokedAt"] is not None
    # Revoking the key that makes the request is allowed.
    first_id = listed[1]["id"]
    assert client.delete(f"/ut/v1/keys/{first_id}", headers={"X-Api-Key": first}).status_code == 204
    problem(client.get("/ut/v1/keys", headers={"X-Api-Key": first}), 401, "invalid_api_key")


# ---------------------------------------------------------------- /rest pipeline

probe = SubsonicRouter()


@probe.endpoint("whoami")
def whoami(req: SubsonicRequest) -> Mapping[str, object]:
    return {"whoami": {"username": req.user.username}}


@pytest.fixture
def rest(services: Services) -> Iterator[TestClient]:
    app = FastAPI()
    app.state.services = services
    app.include_router(build_rest_router([probe]))
    with TestClient(app) as test_client:
        yield test_client


def subsonic_error(r: object) -> Mapping[str, object]:
    assert getattr(r, "status_code", None) == 200
    body = r.json()["subsonic-response"]  # type: ignore[attr-defined]
    assert body["status"] == "failed"
    error: Mapping[str, object] = body["error"]
    return error


def test_rest_auth_rules(rest: TestClient, services: Services) -> None:
    assert isinstance(services.authenticator, AuthService)
    services.authenticator.create_user("alice", ADMIN_PASSWORD, "admin", actor=None)
    user = services.authenticator.list_users()[0]
    key = services.authenticator.create_key(user.id, "Phone", actor=None).secret

    ok = rest.get("/rest/whoami", params={"apiKey": key, "f": "json"})
    assert ok.json()["subsonic-response"]["whoami"] == {"username": "alice"}
    form = rest.post("/rest/whoami.view", data={"u": "alice", "p": "enc:" + key.encode().hex()})
    assert '<whoami username="alice"/>' in form.text

    cases = [
        ({"apiKey": key, "u": "alice"}, 43),
        ({"u": "alice", "t": "abc", "s": "def"}, 42),
        ({"apiKey": UNKNOWN_KEY}, 44),
        ({"u": "alice", "p": ADMIN_PASSWORD}, 40),
        ({}, 10),
    ]
    for creds, code in cases:
        error = subsonic_error(rest.get("/rest/whoami", params={**creds, "f": "json"}))
        assert error["code"] == code
        if code in {42, 44}:
            assert error["helpUrl"] == HELP_URL
    xml = rest.get("/rest/whoami", params={"apiKey": UNKNOWN_KEY})
    assert f'<error code="44" message="Invalid API key" helpUrl="{HELP_URL}"/>' in xml.text


def test_rest_lockout_is_http_429(rest: TestClient, services: Services) -> None:
    for _ in range(10):
        rest.get("/rest/whoami", params={"apiKey": UNKNOWN_KEY, "f": "json"})
    r = rest.get("/rest/whoami", params={"apiKey": UNKNOWN_KEY, "f": "json"})
    assert r.status_code == 429
    assert r.headers["retry-after"] == "60"
    assert r.json()["subsonic-response"]["error"]["code"] == 0


# ---------------------------------------------------------------- install and bootstrap


def test_install_builds_a_service_when_the_authenticator_is_another(
    migrated_settings: Settings,
) -> None:
    services = build_services(migrated_settings)

    class Other:
        def authenticate_subsonic(self, params: object, client_ip: str | None) -> None:
            raise AssertionError

        def authenticate_api_key(self, *args: object) -> None:
            raise AssertionError

    services.authenticator = Other()  # type: ignore[assignment]
    app = FastAPI()
    web.install(app, services)
    assert isinstance(app.state.auth, AuthService)
    services.db.close()


def test_bootstrap_from_env(
    migrated_settings: Settings,
    clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("DEBUG")
    password = "bootstrap admin passphrase"
    monkeypatch.setenv("UT_BOOTSTRAP_ADMIN_USERNAME", "Root")
    monkeypatch.setenv("UT_BOOTSTRAP_ADMIN_PASSWORD", password)
    for _ in range(2):  # the second start finds a user and changes nothing
        services = auth_services(migrated_settings, clock)
        with TestClient(create_app(services=services)) as c:
            r = c.post("/ut/v1/keys", json={"username": "root", "password": password, "name": "x"})
            assert r.status_code == 201
            assert isinstance(services.authenticator, AuthService)
            (admin,) = services.authenticator.list_users()
    assert (admin.username, admin.role) == ("root", "admin")
    assert caplog.text.count("bootstrap admin Root created from the environment") == 1
    # Audit L5: the second start says the password should go.
    assert caplog.text.count("UT_BOOTSTRAP_ADMIN_PASSWORD is still set") == 1
    assert password not in caplog.text


def test_bootstrap_password_from_a_docker_secret_file(
    service: AuthService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Audit L5: no password in the environment; compose mounts it as a secret file."""
    monkeypatch.delenv("UT_BOOTSTRAP_ADMIN_PASSWORD", raising=False)
    (tmp_path / "ut_bootstrap_admin_password").write_text("a secret file passphrase\n")
    settings = AuthSettings(bootstrap_admin_username="root", _secrets_dir=tmp_path)
    assert web.bootstrap_from_env(service, settings)
    assert service.verify_password("root", "a secret file passphrase", "192.0.2.1").role == "admin"


def test_bootstrap_from_env_needs_both_variables(service: AuthService) -> None:
    assert not web.bootstrap_from_env(service, AuthSettings(bootstrap_admin_username="root"))
    only_password = AuthSettings(bootstrap_admin_password=SecretStr("a long secret here"))
    assert not web.bootstrap_from_env(service, only_password)
    assert service.list_users() == []
