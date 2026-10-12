# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""A live api (uvicorn on a loopback port, in the test's event loop) for streaming tests.

Streaming while downloading is about bytes arriving over time and transfers cut halfway, which
an in-process ASGI transport (it buffers whole responses) cannot show. So the app runs on a
real socket, and the tests read responses as they grow. The job is driven by hand (`Download`:
claim, write, report, finish, fail through `JobQueue`) or by the real worker loop against the
same server. Users: ana (`apiKey=utk_ana`) and bob (`apiKey=utk_bob`).
"""

import asyncio
import socket
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import anyio
import httpx
import uvicorn
from pydantic import SecretStr

from ultimatetunes.app import create_app
from ultimatetunes.core.authn import Principal
from ultimatetunes.core.clock import FakeClock, format_ts
from ultimatetunes.core.services import Services, build_services
from ultimatetunes.errors import InvalidApiKey
from ultimatetunes.jobs.queue import Claimed, Job, ProgressReport
from ultimatetunes.settings import Settings

TOKEN = "streaming-test-worker-token-0123456789abcdef"
VIDEO = "Rb8Tn3ZcYv0"  # "Glass Orchard" in the fake catalog
OTHER_VIDEO = "Wq5Jd7HsKe2"
ANA = Principal("0199d6a2-4c1e-7b3a-9f10-2a6c8e01e001", "ana", "user", "k-ana")
BOB = Principal("0199d6a2-4c1e-7b3a-9f10-2a6c8e01e002", "bob", "user", "k-bob")
CARL = Principal("0199d6a2-4c1e-7b3a-9f10-2a6c8e01e003", "carl", "user", None)
KEYS = {"utk_ana": ANA, "utk_bob": BOB, "carl-password": CARL}
AUDIO = bytes(range(256)) * 4  # 1024 bytes standing in for a WebM download
WAIT_S = 5.0


class Keys:
    """Stands in for T04 (tested in tests/auth): the key (or password) names the user."""

    def authenticate_subsonic(
        self, params: Mapping[str, Sequence[str]], client_ip: str | None
    ) -> Principal:
        key = (params.get("apiKey") or params.get("p") or [""])[0]
        if key not in KEYS:
            raise InvalidApiKey()
        return KEYS[key]

    def authenticate_api_key(
        self, header_key: str | None, query_key: str | None, client_ip: str | None
    ) -> Principal:
        key = header_key or query_key or ""
        if key not in KEYS:
            raise InvalidApiKey()
        return KEYS[key]


@dataclass
class Live:
    services: Services
    clock: FakeClock
    url: str
    client: httpx.AsyncClient
    client_app: Any

    def song(self, video: str = VIDEO) -> str:
        return f"yt:{video}"

    def params(self, song: str, key: str = "utk_ana", **extra: str) -> dict[str, str]:
        return {"apiKey": key, "id": song, "f": "json", **extra}

    def job(self, video: str = VIDEO) -> Job | None:
        return self.services.jobs.by_video(video)

    def one(self, sql: str, params: Sequence[object] = ()) -> Any:
        with self.services.db.read() as conn:
            return conn.execute(sql, params).scalar()

    def listeners(self, job_id: str) -> int:
        return self.services.inflight.listeners(f"stream:job:{job_id}")

    def download(self, video: str = VIDEO) -> "Download":
        claimed = self.services.jobs.claim("w1", lease_s=300)
        assert claimed is not None
        assert claimed.job.yt_video_id == video
        return Download(self, claimed)


@dataclass
class Download:
    """One attempt, driven by hand like a worker would (write, then report)."""

    live: Live
    claimed: Claimed
    written: int = 0
    format_id: str = "251"
    content_type: str = "audio/webm"
    expected_size: int | None = len(AUDIO)
    progressive: bool = True
    data: bytes = AUDIO
    finished: bool = False

    @property
    def job_id(self) -> str:
        return self.claimed.job.id

    @property
    def lease(self) -> str:
        return self.claimed.lease.lease_id

    @property
    def part(self) -> str:
        return f"{self.claimed.job.staging_dir}/{VIDEO}.webm.part"

    @property
    def final(self) -> str:
        return f"{self.claimed.job.staging_dir}/{VIDEO}.webm"

    def report(self, *, state: str = "downloading") -> None:
        self.live.services.jobs.progress(
            self.job_id,
            self.lease,
            ProgressReport(
                state=state,
                progress=self.written / len(self.data),
                bytes_downloaded=self.written,
                expected_size=self.expected_size,
                part_path=self.part,
                final_path=self.final,
                finished=self.finished,
                format_id=self.format_id,
                content_type=self.content_type,
                progressive=self.progressive,
            ),
        )

    def write(self, count: int, *, report: bool = True) -> None:
        staging = self.live.services.staging
        with staging.open_write(self.part, append=True) as out:
            out.write(self.data[self.written : self.written + count])
        self.written = min(len(self.data), self.written + count)
        if report:
            self.report()

    def finish(self) -> None:
        self.write(len(self.data) - self.written, report=False)
        self.live.services.staging.rename(self.part, self.final)
        self.finished = True
        self.report(state="tagging")

    def fail(self, code: str = "video_unavailable", *, retryable: bool = False) -> None:
        self.live.services.jobs.fail(
            self.job_id, self.lease, error_code=code, retryable=retryable, message="test failure"
        )


@dataclass
class Listening:
    """A `GET` read in the background as it grows."""

    status: int | None = None
    headers: httpx.Headers = field(default_factory=httpx.Headers)
    body: bytearray = field(default_factory=bytearray)
    error: Exception | None = None
    started: anyio.Event = field(default_factory=anyio.Event)
    done: anyio.Event = field(default_factory=anyio.Event)
    stop: anyio.Event = field(default_factory=anyio.Event)

    async def run(
        self, client: httpx.AsyncClient, path: str, params: dict[str, str], headers: dict[str, str]
    ) -> None:
        try:
            async with client.stream("GET", path, params=params, headers=headers) as response:
                self.status = response.status_code
                self.headers = response.headers
                self.started.set()
                async with anyio.create_task_group() as group:

                    async def read() -> None:
                        try:
                            async for chunk in response.aiter_raw():
                                self.body.extend(chunk)
                        except httpx.HTTPError as exc:
                            self.error = exc
                        group.cancel_scope.cancel()

                    async def hang_up() -> None:
                        await self.stop.wait()
                        group.cancel_scope.cancel()

                    group.start_soon(read)
                    group.start_soon(hang_up)
        except httpx.HTTPError as exc:
            self.error = exc
        finally:
            self.started.set()
            self.done.set()


async def until(check: Callable[[], bool]) -> None:
    """Waits (at most `WAIT_S`) for a condition on state the server owns."""
    with anyio.fail_after(WAIT_S):
        while not check():  # noqa: ASYNC110 - the state lives in another task's objects
            await anyio.sleep(0.01)


@asynccontextmanager
async def serve(
    settings: Settings, clock: FakeClock, *, setup: Callable[[Services], None] | None = None
) -> AsyncIterator[Live]:
    configured = settings.model_copy(update={"worker_token": SecretStr(TOKEN)})
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
    if setup is not None:
        setup(services)
    app = create_app(services=services)
    server = uvicorn.Server(uvicorn.Config(app, lifespan="off", log_config=None, access_log=False))
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    task = asyncio.ensure_future(server.serve(sockets=[sock]))
    try:
        await until(lambda: server.started)
        url = f"http://127.0.0.1:{port}"
        async with httpx.AsyncClient(base_url=url, timeout=WAIT_S) as client:
            yield Live(services, clock, url, client, app)
    finally:
        server.should_exit = True
        server.force_exit = True
        await task
        sock.close()
        services.db.close()
