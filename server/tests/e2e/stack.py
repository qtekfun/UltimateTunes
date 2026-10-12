# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Drives the running end-to-end stack (PLAN T20): HTTP clients and the Docker Compose project.

The stack is `server/compose.test.yaml` + `tools/e2e/compose.e2e.yaml` (fake YouTube, never a
real download), brought up by `tools/e2e/run.sh` or by the `e2e` workflow. These helpers never
start it themselves; they only talk to it over HTTP and stop/start its worker container.
"""

import os
import re
import shutil
import subprocess  # nosec B404 - argument lists only, fixed commands
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx

REPO = Path(__file__).resolve().parents[3]
COMPOSE_FILES = (REPO / "server" / "compose.test.yaml", REPO / "tools" / "e2e" / "compose.e2e.yaml")
CSRF = re.compile(r'name="csrf" value="([^"]+)"')

# Fixed, public, worthless credentials of the throwaway test stack (never a real deployment).
ADMIN_USERNAME = "e2eadmin"
ADMIN_PASSWORD = "e2e-admin-password-not-a-secret"


def env_url() -> str:
    port = os.environ.get("UT_E2E_PORT", "8044")
    return os.environ.get("UT_E2E_URL", f"http://127.0.0.1:{port}")


def wait_until[T](
    probe: Callable[[], T | None], *, timeout_s: float, what: str, every_s: float = 0.5
) -> T:
    """Calls `probe` until it returns something other than None, or fails after `timeout_s`."""
    deadline = time.monotonic() + timeout_s
    while True:
        value = probe()
        if value is not None:
            return value
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out after {timeout_s} s waiting for {what}")
        time.sleep(every_s)


@dataclass(frozen=True)
class Compose:
    """The Docker Compose project of the stack (`UT_E2E_PROJECT`, default `ut-e2e`)."""

    project: str

    def run(self, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
        docker = shutil.which("docker")
        if docker is None:
            raise AssertionError("docker is not installed")
        files = [arg for path in COMPOSE_FILES for arg in ("-f", str(path))]
        return subprocess.run(  # noqa: S603 - fixed argument list, no shell  # nosec B603
            [docker, "compose", "-p", self.project, *files, *args],
            input=stdin,
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )

    def bootstrap_admin(self) -> None:
        """Creates the admin once; a second call finds users and changes nothing."""
        done = self.run(
            "exec",
            "-T",
            "-e",
            f"UT_BOOTSTRAP_ADMIN_PASSWORD={ADMIN_PASSWORD}",
            "api",
            "ultimatetunes",
            "bootstrap-admin",
            ADMIN_USERNAME,
        )
        if done.returncode != 0 and "already exist" not in done.stderr:
            raise AssertionError(f"bootstrap-admin failed: {done.stderr.strip()}")

    def kill(self, service: str) -> None:
        """SIGKILL: the process gets no chance to release its lease."""
        self._check(self.run("kill", "-s", "SIGKILL", service), f"kill {service}")

    def start(self, service: str) -> None:
        self._check(self.run("start", service), f"start {service}")

    def is_running(self, service: str) -> bool:
        done = self.run("ps", "--status", "running", "--services")
        return service in done.stdout.split()

    @staticmethod
    def _check(done: subprocess.CompletedProcess[str], what: str) -> None:
        if done.returncode != 0:
            raise AssertionError(f"docker compose {what} failed: {done.stderr.strip()}")


class Client:
    """One device of one user: `/rest` with `apiKey`, `/ut/v1` with `X-Api-Key`."""

    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.http = httpx.Client(base_url=base_url, timeout=30.0)

    def close(self) -> None:
        self.http.close()

    def rest_raw(self, endpoint: str, /, **params: Any) -> dict[str, Any]:
        """The `subsonic-response` of `/rest/<endpoint>`, whatever its status."""
        query = {"f": "json", "apiKey": self.api_key, "c": "ut-e2e", "v": "1.16.1", **params}
        answer = self.http.get(f"/rest/{endpoint}", params=query)
        answer.raise_for_status()
        return cast("dict[str, Any]", answer.json()["subsonic-response"])

    def rest(self, endpoint: str, /, **params: Any) -> dict[str, Any]:
        body = self.rest_raw(endpoint, **params)
        assert body["status"] == "ok", f"{endpoint}: {body.get('error')}"
        return body

    def ut(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        return self.http.request(
            method, f"/ut/v1{path}", headers={"X-Api-Key": self.api_key}, **kwargs
        )

    def ut_json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        answer = self.ut(method, path, **kwargs)
        assert answer.is_success, f"{method} {path}: {answer.status_code} {answer.text}"
        return cast("dict[str, Any]", answer.json())

    def status(self, song_id: str) -> dict[str, Any]:
        return self.ut_json("GET", f"/tracks/{song_id}/status")

    def wait_ready(self, song_id: str, *, timeout_s: float = 90.0) -> dict[str, Any]:
        def ready() -> dict[str, Any] | None:
            status = self.status(song_id)
            assert status["state"] not in ("failed", "cancelled"), status
            return status if status["state"] == "ready" else None

        return wait_until(ready, timeout_s=timeout_s, what=f"{song_id} ready", every_s=1.0)

    def search_tracks(self, query: str) -> list[dict[str, Any]]:
        found = self.ut_json("GET", "/search", params={"q": query})
        return cast("list[dict[str, Any]]", found["tracks"])

    @contextmanager
    def stream(
        self, song_id: str, headers: Mapping[str, str] | None = None
    ) -> Iterator[httpx.Response]:
        params = {"id": song_id, "apiKey": self.api_key, "c": "ut-e2e", "v": "1.16.1"}
        with self.http.stream(
            "GET", "/rest/stream", params=params, headers=dict(headers or {})
        ) as answer:
            yield answer


class AdminPanel:
    """The admin panel (`/admin`), driven like a browser: login form, session cookie, CSRF.

    The panel's cookies are `Secure`, which httpx's cookie jar never sends over plain HTTP, so
    they are carried by hand (the test stack has no TLS; SPEC section 11, T15).
    """

    def __init__(self, base_url: str) -> None:
        self.http = httpx.Client(base_url=base_url, timeout=30.0, follow_redirects=False)
        self.cookies: dict[str, str] = {}

    def close(self) -> None:
        self.http.close()

    def _keep(self, answer: httpx.Response) -> None:
        for name, value in answer.cookies.items():
            self.cookies[name] = value

    def _headers(self) -> dict[str, str]:
        jar = "; ".join(f"{name}={value}" for name, value in self.cookies.items())
        return {"Cookie": jar, "Sec-Fetch-Site": "same-origin"}

    def _csrf(self, path: str) -> str:
        page = self.http.get(path, headers=self._headers())
        assert page.status_code == 200, f"GET {path}: {page.status_code}"
        self._keep(page)
        found = CSRF.search(page.text)
        assert found is not None, f"no CSRF token on {path}"
        return found.group(1)

    def login(self, username: str, password: str) -> None:
        token = self._csrf("/admin/login")
        answer = self.http.post(
            "/admin/login",
            data={"csrf": token, "username": username, "password": password},
            headers=self._headers(),
        )
        assert answer.status_code == 303, f"admin login: {answer.status_code}"
        self._keep(answer)

    def create_user(self, username: str, password: str, role: str = "user") -> None:
        """Creates the user unless the list already shows it (a rerun on the same stack)."""
        token = self._csrf("/admin/users")
        if f">{username}<" in self.http.get("/admin/users", headers=self._headers()).text:
            return
        answer = self.http.post(
            "/admin/users",
            data={"csrf": token, "username": username, "password": password, "role": role},
            headers=self._headers(),
        )
        assert answer.status_code in (200, 303), f"create user: {answer.status_code}"
        listing = self.http.get("/admin/users", headers=self._headers())
        assert username in listing.text, f"user {username} not listed after creation"


def create_key(base_url: str, username: str, password: str, name: str) -> str:
    """`POST /ut/v1/keys` with username and password: the new key's secret."""
    answer = httpx.post(
        f"{base_url}/ut/v1/keys",
        json={"username": username, "password": password, "name": name},
        timeout=30.0,
    )
    assert answer.status_code == 201, f"create key: {answer.status_code} {answer.text}"
    assert answer.headers.get("cache-control") == "no-store"
    return cast("str", answer.json()["secret"])
