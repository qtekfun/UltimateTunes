# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The client and internal listeners (listeners.py, T22): `/internal/v1` never on the client
port, nothing else on the internal one, one signal stops both."""

import asyncio
from types import SimpleNamespace
from typing import Any

import anyio
import pytest
import uvicorn
from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.websockets import WebSocketDisconnect

from ultimatetunes import cli, listeners
from ultimatetunes.app import create_app
from ultimatetunes.settings import Settings

TOKEN = "listener-test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def clients(settings: Settings) -> tuple[TestClient, TestClient]:
    app = create_app(settings.model_copy(update={"worker_token": SecretStr(TOKEN)}))
    return (
        TestClient(listeners.Listener(app, internal=False), client=("127.0.0.1", 1)),
        TestClient(listeners.Listener(app, internal=True), client=("127.0.0.1", 1)),
    )


def test_the_worker_api_is_only_on_the_internal_listener(settings: Settings) -> None:
    public, internal = clients(settings)
    # The client port does not even admit the worker API exists (no 401, no problem body).
    r = public.post("/internal/v1/jobs/claim", headers=AUTH, json={})
    assert (r.status_code, r.text) == (404, "Not Found")
    assert public.get("/internal").status_code == 404
    # The internal port answers it (here: a validation problem, past the token check) ...
    r = internal.post("/internal/v1/jobs/claim", headers=AUTH, json={})
    assert r.status_code != 404
    assert r.headers["content-type"].startswith("application/problem+json")
    # ... and nothing else, except the liveness probe.
    for path in ("/", "/rest/ping", "/ut/v1/server", "/admin", "/readyz"):
        assert internal.get(path).status_code == 404, path
    assert internal.get("/healthz").json() == {"status": "ok"}
    assert public.get("/healthz").json() == {"status": "ok"}


def test_websockets_for_the_other_listener_are_closed(settings: Settings) -> None:
    public, _internal = clients(settings)
    with (
        pytest.raises(WebSocketDisconnect) as closed,
        public.websocket_connect("/internal/v1/ws"),
    ):
        pass  # pragma: no cover - never accepted
    assert closed.value.code == 1008


def test_is_internal_path() -> None:
    assert listeners.is_internal_path("/internal")
    assert listeners.is_internal_path("/internal/v1/jobs")
    assert not listeners.is_internal_path("/internals")
    assert not listeners.is_internal_path("/rest/internal/x")


async def _app(scope: Any, receive: Any, send: Any) -> None:  # pragma: no cover - never run
    return


@pytest.mark.anyio
async def test_the_follower_stops_with_its_leader() -> None:
    leader = uvicorn.Server(uvicorn.Config(_app))
    follower = listeners.Follower(uvicorn.Config(_app), leader)
    with follower.capture_signals():
        pass
    assert await follower.on_tick(1) is False
    leader.should_exit = True
    assert await follower.on_tick(1) is True
    assert follower.should_exit


def test_run_api_serves_two_listeners(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, uvicorn.Config] = {}

    async def fake_serve(client: uvicorn.Config, internal: uvicorn.Config) -> None:
        seen["client"], seen["internal"] = client, internal

    monkeypatch.setattr(listeners, "serve", fake_serve)
    configured = settings.model_copy(update={"host": "0.0.0.0", "internal_port": 9045})  # noqa: S104
    assert cli.run_api(configured) == 0
    client, internal = seen["client"], seen["internal"]
    assert (client.host, client.port, client.lifespan) == ("0.0.0.0", 8044, "on")  # noqa: S104
    assert (internal.host, internal.port, internal.lifespan) == ("0.0.0.0", 9045, "off")  # noqa: S104
    for config in (client, internal):
        assert config.proxy_headers is False
        assert config.server_header is False
        assert config.log_config is None
        assert config.timeout_graceful_shutdown == settings.shutdown_timeout_s
        assert config.timeout_keep_alive == settings.keepalive_timeout_s == 5
        assert config.backlog == settings.backlog == 256
        assert config.h11_max_incomplete_event_size == settings.max_header_bytes == 16384
        assert config.http == "h11"
    assert client.limit_concurrency == settings.limit_concurrency == 128
    assert internal.limit_concurrency == settings.internal_limit_concurrency == 32
    assert isinstance(client.app, listeners.Listener)
    assert not client.app.internal
    assert isinstance(internal.app, listeners.Listener)
    assert internal.app.internal
    assert client.app.app is internal.app.app  # one app, one set of services


def test_run_api_refuses_one_port_for_both(settings: Settings) -> None:
    with pytest.raises(SystemExit, match="UT_INTERNAL_PORT"):
        cli.run_api(settings.model_copy(update={"internal_port": settings.port}))


def test_internal_host_defaults_to_the_host(settings: Settings) -> None:
    assert settings.internal_bind == settings.host
    assert settings.model_copy(update={"internal_host": "10.0.0.2"}).internal_bind == "10.0.0.2"


def test_trusted_proxies_must_be_networks() -> None:
    with pytest.raises(ValueError, match="does not appear to be an IPv4 or IPv6 network"):
        Settings(trusted_proxies="proxy.example")


@pytest.mark.anyio
async def test_the_lifespan_ends_only_after_the_internal_listener_drained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []

    async def base_shutdown(self: uvicorn.Server, sockets: Any = None) -> None:
        order.append("lifespan shutdown")

    monkeypatch.setattr(uvicorn.Server, "shutdown", base_shutdown)

    async def drain() -> None:
        await asyncio.sleep(0.01)
        order.append("internal drained")

    leader = listeners.Leader(uvicorn.Config(_app))
    closed: list[bool] = []
    leader.servers = [SimpleNamespace(close=lambda: closed.append(True))]  # type: ignore[list-item]
    leader.follower = asyncio.ensure_future(drain())
    await leader.shutdown()
    assert closed == [True]  # stopped accepting first
    assert order == ["internal drained", "lifespan shutdown"]


@pytest.mark.anyio
async def test_a_failing_internal_listener_stops_the_client_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def follower_fails(self: listeners.Follower, sockets: Any = None) -> None:
        raise RuntimeError("port 8045 in use")

    stopped: list[bool] = []

    async def leader_runs(self: listeners.Leader, sockets: Any = None) -> None:
        assert self.follower is not None
        with anyio.fail_after(5):
            await asyncio.wait([self.follower])
        await asyncio.sleep(0)  # the done callback runs on the next loop turn
        stopped.append(self.should_exit)

    monkeypatch.setattr(listeners.Follower, "serve", follower_fails)
    monkeypatch.setattr(listeners.Leader, "serve", leader_runs)
    with pytest.raises(RuntimeError, match="8045"):
        await listeners.serve(uvicorn.Config(_app), uvicorn.Config(_app))
    assert stopped == [True]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
