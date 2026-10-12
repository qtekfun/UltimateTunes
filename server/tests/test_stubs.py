# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Every contract operation is routed.

Until its task lands an operation answers "not implemented" (error 0 / HTTP 501); once a stream
implements it, it may answer anything valid for its contract, but never "unknown endpoint" and
never a framework 404/405. Streams therefore never edit this shared file.
"""

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]  # dev-only, via schemathesis
from fastapi import APIRouter
from fastapi.testclient import TestClient
from pydantic import BaseModel, SecretStr

from ultimatetunes.app import create_app
from ultimatetunes.core.authn import Principal
from ultimatetunes.core.services import build_services
from ultimatetunes.settings import Settings

OPENAPI = Path(__file__).resolve().parents[2] / "contracts" / "openapi"
TOKEN = "worker-token-for-tests-0123456789abcdef"


def operations(name: str) -> list[tuple[str, str]]:
    spec: dict[str, Any] = yaml.safe_load((OPENAPI / name).read_text(encoding="utf-8"))
    return [
        (method.upper(), re.sub(r"\{[^}]+\}", "0199d6a2-4c1e-7b3a-9f10-2a6c8e01c001", path))
        for path, item in spec["paths"].items()
        for method in item
        if method in {"get", "post", "put", "delete"}
    ]


class AllowAll:
    """Stands in for T04: lets every call reach the stub handler itself."""

    principal = Principal("0199d6a2-4c1e-7b3a-9f10-2a6c8e01e001", "ana", "admin")

    def authenticate_subsonic(self, params: object, client_ip: str | None) -> Principal:
        return self.principal

    def authenticate_api_key(
        self, header_key: str | None, query_key: str | None, client_ip: str | None
    ) -> Principal:
        return self.principal


@pytest.fixture(params=["pending-auth", "allow-all"])
def client(request: pytest.FixtureRequest, settings: Settings) -> Iterator[TestClient]:
    configured = settings.model_copy(update={"worker_token": SecretStr(TOKEN)})
    services = build_services(configured)
    if request.param == "allow-all":
        services.authenticator = AllowAll()
        assert AllowAll.principal.is_admin
    with TestClient(create_app(services=services), raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.mark.parametrize(("method", "path"), operations("opensubsonic-subset.yaml"))
@pytest.mark.parametrize("fmt", ["json", "xml"])
def test_opensubsonic_stubs(client: TestClient, method: str, path: str, fmt: str) -> None:
    for url in (path, f"{path}.view"):
        if method == "GET":
            r = client.get(url, params={"f": fmt, "apiKey": "utk_x"})
        else:
            r = client.post(url, data={"f": fmt, "apiKey": "utk_x"})
        assert r.status_code not in (404, 405) or "subsonic-response" in r.text
        assert "Unknown endpoint" not in r.text
        if r.status_code == 501:
            if fmt == "json":
                assert r.json()["subsonic-response"]["error"]["code"] == 0
            else:
                assert '<error code="0"' in r.text


@pytest.mark.parametrize("name", ["stream", "download", "getCoverArt"])
def test_binary_stubs_answer_head(client: TestClient, name: str) -> None:
    r = client.head(f"/rest/{name}", params={"apiKey": "utk_x", "id": "yt:Qx7Lm2pZ0aB"})
    assert r.status_code != 405
    assert r.content == b""


@pytest.mark.parametrize(("method", "path"), operations("ut-v1.yaml"))
def test_ut_v1_stubs(client: TestClient, method: str, path: str) -> None:
    r = client.request(method, path, headers={"X-Api-Key": "utk_x"})
    assert r.status_code != 405
    if r.status_code == 404:  # an implemented route may say "not_found" for the fake id
        assert r.json()["code"] == "not_found"
    if r.status_code == 501:
        assert r.headers["content-type"] == "application/problem+json"
        assert r.json()["code"] == "not_implemented"
        assert r.json()["instance"] == path


@pytest.mark.parametrize(("method", "path"), operations("internal-worker.yaml"))
def test_internal_stubs_need_the_worker_token(client: TestClient, method: str, path: str) -> None:
    assert client.request(method, path).json()["code"] == "invalid_worker_token"
    wrong = client.request(method, path, headers={"Authorization": f"Bearer {TOKEN}x"})
    assert wrong.status_code == 401
    r = client.request(method, path, headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code not in (401, 405)
    if r.status_code == 404:
        assert r.json()["code"] == "not_found"
    if r.status_code == 501:
        assert r.json()["code"] == "not_implemented"


def test_internal_api_is_closed_without_a_configured_token(settings: Settings) -> None:
    with TestClient(create_app(settings)) as c:
        r = c.post("/internal/v1/jobs/claim", headers={"Authorization": "Bearer "})
    assert r.status_code == 401
    assert r.json()["detail"] == "Bearer token missing or wrong"


def test_admin_is_routed(client: TestClient) -> None:
    """`/admin` is routed: the T02 placeholder (501) or the real panel, which may refuse the
    test client's address (allowlist, 403) or ask for a login, but never 404/405 or a crash."""
    for path in ("/admin", "/admin/users"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code not in (404, 405)
        assert r.status_code < 500 or r.status_code == 501


def test_validation_and_unexpected_errors_are_problems(settings: Settings) -> None:
    class Body(BaseModel):
        n: int

    extra = APIRouter()

    @extra.post("/ut/v1/_test/validate")
    def validate(body: Body) -> int:
        return body.n

    @extra.get("/ut/v1/_test/crash")
    def crash() -> None:
        raise RuntimeError("boom")

    services = build_services(settings)
    app = create_app(services=services)
    app.include_router(extra)
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.post("/ut/v1/_test/validate", json={"n": "x"})
        assert r.status_code == 400
        assert r.json()["code"] == "invalid_parameter"
        r = c.get("/ut/v1/_test/crash")
        assert r.status_code == 500
        assert r.json()["code"] == "internal_error"
