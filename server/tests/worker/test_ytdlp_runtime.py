# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The zipapp volume: seed install, verified update (GitHub mocked, gpgv and the smoke test
faked), atomic swap, pruning, and every refusal."""

import hashlib
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from subprocess import CompletedProcess

import anyio
import httpx
import pytest

from ultimatetunes.core.clock import FakeClock
from ultimatetunes.worker.settings import YTDLP_KEY_FINGERPRINT, WorkerSettings
from ultimatetunes.worker.ytdlp_runtime import UpdateError, YtDlpRuntime, _run

pytestmark = pytest.mark.anyio
NEW = "2026.09.28"
SEED = "2026.08.19"
ZIPAPP = b"PK\x03\x04 a pretend zipapp"
VALIDSIG = (
    f"[GNUPG:] NEWSIG\n[GNUPG:] GOODSIG 57CF65933B5A7581 yt-dlp\n"
    f"[GNUPG:] VALIDSIG {YTDLP_KEY_FINGERPRINT} 2026-09-28 0 4 0 1 10 00 {YTDLP_KEY_FINGERPRINT}\n"
)
Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def sums(content: bytes = ZIPAPP) -> bytes:
    digest = hashlib.sha256(content).hexdigest()
    return f"{'0' * 64}  yt-dlp.exe\n{digest}  yt-dlp\n".encode()


def github(
    *,
    tag: str = NEW,
    zipapp: bytes = ZIPAPP,
    sums_body: bytes | None = None,
    overrides: dict[str, httpx.Response] | None = None,
) -> Handler:
    """GitHub's API and release downloads, with the asset hops through a redirect."""
    base = f"/yt-dlp/yt-dlp/releases/download/{tag}"
    routes = {
        "api.github.com/repos/yt-dlp/yt-dlp/releases/latest": httpx.Response(
            200, json={"tag_name": tag}
        ),
        f"github.com{base}/yt-dlp": httpx.Response(
            302, headers={"location": "https://release-assets.githubusercontent.com/a/zip"}
        ),
        "release-assets.githubusercontent.com/a/zip": httpx.Response(200, content=zipapp),
        f"github.com{base}/SHA2-256SUMS": httpx.Response(
            200, content=sums(zipapp) if sums_body is None else sums_body
        ),
        f"github.com{base}/SHA2-256SUMS.sig": httpx.Response(200, content=b"sig"),
    }
    routes.update(overrides or {})

    def handle(request: httpx.Request) -> httpx.Response:
        key = f"{request.url.host}{request.url.path}"
        return routes.get(key, httpx.Response(404))

    return handle


class Processes:
    """Fake gpgv and smoke test: records the argument lists."""

    def __init__(self, *, gpgv: str = VALIDSIG, gpgv_code: int = 0, version: str = NEW) -> None:
        self.calls: list[list[str]] = []
        self.gpgv = gpgv
        self.gpgv_code = gpgv_code
        self.version = version

    async def __call__(self, args: Sequence[str]) -> CompletedProcess[bytes]:
        self.calls.append(list(args))
        if args[0].endswith("gpgv"):
            return CompletedProcess(args, self.gpgv_code, self.gpgv.encode(), b"")
        return CompletedProcess(args, 0, f"{self.version}\n".encode(), b"")


@pytest.fixture
def settings(tmp_path: Path) -> WorkerSettings:
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "yt-dlp").write_bytes(b"seed zipapp")
    return WorkerSettings(ytdlp_dir=tmp_path / "ytdlp", ytdlp_seed_dir=seed)


def runtime(
    settings: WorkerSettings, handler: Handler, processes: Processes | None = None
) -> YtDlpRuntime:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return YtDlpRuntime(settings, client=client, run=processes or Processes())


async def test_the_seed_is_installed_once(settings: WorkerSettings) -> None:
    processes = Processes(version=SEED)
    rt = runtime(settings, github(), processes)
    assert rt.current_version() is None
    assert await rt.ensure_installed() == SEED
    assert rt.current_version() == SEED
    assert rt.current_zipapp().read_bytes() == b"seed zipapp"
    assert rt.current_link.readlink() == Path("releases") / SEED
    assert await rt.ensure_installed() == SEED
    assert len(processes.calls) == 1
    assert processes.calls[0][1:3] == ["-I", "-S"]


async def test_no_seed_and_no_install_is_an_error(settings: WorkerSettings) -> None:
    (settings.ytdlp_seed_dir / "yt-dlp").unlink()
    with pytest.raises(UpdateError, match="no seed"):
        await runtime(settings, github()).ensure_installed()


async def test_a_seed_that_fails_its_smoke_test_is_refused(settings: WorkerSettings) -> None:
    with pytest.raises(UpdateError, match="smoke"):
        await runtime(settings, github(), Processes(version="garbage")).ensure_installed()


async def test_an_update_is_verified_then_swapped_in(settings: WorkerSettings) -> None:
    processes = Processes(version=SEED)
    rt = runtime(settings, github(), processes)
    await rt.ensure_installed()
    processes.version = NEW
    result = await rt.update()
    assert (result.version, result.updated) == (NEW, True)
    assert rt.current_version() == NEW
    assert rt.current_zipapp().read_bytes() == ZIPAPP
    release = settings.ytdlp_dir / "releases" / NEW
    assert sorted(p.name for p in release.iterdir()) == ["yt-dlp"]
    gpgv = processes.calls[1]
    assert gpgv[:5] == [
        "/usr/bin/gpgv",
        "--status-fd",
        "1",
        "--keyring",
        str(settings.ytdlp_keyring),
    ]
    assert (settings.ytdlp_dir / "releases" / SEED).is_dir()
    # Already current: nothing to do.
    again = await rt.update()
    assert (again.version, again.updated) == (NEW, False)
    # Forced: reinstalls the same release in place.
    forced = await rt.update(force=True)
    assert forced.updated
    assert rt.current_version() == NEW


async def test_old_releases_are_pruned(settings: WorkerSettings) -> None:
    releases = settings.ytdlp_dir / "releases"
    for tag in ("2026.01.01", "2026.02.01", "2026.03.01"):
        (releases / tag).mkdir(parents=True)
    await runtime(settings, github()).update()
    assert sorted(p.name for p in releases.iterdir()) == ["2026.02.01", "2026.03.01", NEW]


async def test_the_nightly_channel_reads_the_nightly_repository(tmp_path: Path) -> None:
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json={"tag_name": "2026.10.10.233141"})

    nightly = WorkerSettings(ytdlp_dir=tmp_path / "y", ytdlp_channel="nightly")
    with pytest.raises(UpdateError):
        await runtime(nightly, handle).update()
    assert seen[0] == "/repos/yt-dlp/yt-dlp-nightly-builds/releases/latest"


@pytest.mark.parametrize(
    ("handler", "processes", "match"),
    [
        (github(tag="latest"), None, "unexpected release tag"),
        (
            github(
                overrides={
                    "api.github.com/repos/yt-dlp/yt-dlp/releases/latest": httpx.Response(
                        200, content=b"not json"
                    )
                }
            ),
            None,
            "unexpected GitHub",
        ),
        (
            github(
                overrides={
                    "api.github.com/repos/yt-dlp/yt-dlp/releases/latest": httpx.Response(503)
                }
            ),
            None,
            "answered 503",
        ),
        (github(sums_body=b"deadbeef  yt-dlp\n"), None, "SHA-256"),
        (github(sums_body=b"nothing useful\n"), None, "SHA-256"),
        (github(), Processes(gpgv="[GNUPG:] BADSIG 57CF65933B5A7581\n"), "signature"),
        (github(), Processes(gpgv=VALIDSIG.replace("AC0C", "FFFF")), "signature"),
        (github(), Processes(gpgv_code=2), "signature"),
        (github(), Processes(gpgv="[GNUPG:] VALIDSIG\n"), "signature"),
        (github(), Processes(version="2026.01.01"), "expected"),
        (
            github(
                overrides={
                    "release-assets.githubusercontent.com/a/zip": httpx.Response(
                        200, content=b"x" * (51 * 1024 * 1024)
                    )
                }
            ),
            None,
            "larger",
        ),
    ],
)
async def test_refusals_keep_the_current_release(
    settings: WorkerSettings, handler: Handler, processes: Processes | None, match: str
) -> None:
    seeded = runtime(settings, github(), Processes(version=SEED))
    await seeded.ensure_installed()
    with pytest.raises(UpdateError, match=match):
        await runtime(settings, handler, processes).update()
    assert seeded.current_version() == SEED


@pytest.mark.parametrize(
    "location",
    [
        "http://release-assets.githubusercontent.com/a/zip",
        "https://evil.example/zip",
        "https://github.com/loop",
    ],
)
async def test_redirects_stay_on_the_approved_https_hosts(
    settings: WorkerSettings, location: str
) -> None:
    base = f"github.com/yt-dlp/yt-dlp/releases/download/{NEW}"
    loop = {"github.com/loop": httpx.Response(302, headers={"location": "/loop"})}
    handler = github(
        overrides={f"{base}/yt-dlp": httpx.Response(302, headers={"location": location})} | loop
    )
    with pytest.raises(UpdateError, match=r"refusing|redirects"):
        await runtime(settings, handler).update()


async def test_transport_errors_become_update_errors(settings: WorkerSettings) -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    with pytest.raises(UpdateError, match="ConnectError"):
        await runtime(settings, broken).update()


async def test_without_a_client_one_is_opened_per_call(
    settings: WorkerSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[httpx.AsyncClient] = []
    real = httpx.AsyncClient

    def factory(**kwargs: object) -> httpx.AsyncClient:
        client = real(transport=httpx.MockTransport(github(tag="bad")))
        opened.append(client)
        return client

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    rt = YtDlpRuntime(settings, run=Processes())
    with pytest.raises(UpdateError):
        await rt.update()
    assert len(opened) == 1
    assert opened[0].is_closed


async def test_a_link_to_something_else_is_not_a_version(settings: WorkerSettings) -> None:
    rt = runtime(settings, github())
    target = settings.ytdlp_dir / "releases" / "weird"
    target.mkdir(parents=True)
    (target / "yt-dlp").write_bytes(b"x")
    rt.current_link.symlink_to(Path("releases") / "weird")
    assert rt.current_version() is None


async def test_the_default_runner_uses_an_argument_list() -> None:
    result = await _run([sys.executable, "-c", "print(7)"])
    assert (result.returncode, result.stdout.strip()) == (0, b"7")


async def test_the_last_check_is_persisted(settings: WorkerSettings) -> None:
    clock = FakeClock()
    client = httpx.AsyncClient(transport=httpx.MockTransport(github()))
    rt = YtDlpRuntime(settings, client=client, run=Processes(), clock=clock)
    assert rt.last_check() is None
    assert rt.update_due(3600)
    await rt.update()
    assert rt.last_check() == clock.now()
    clock.advance(1800)
    # A restarted worker reads the same file.
    again = YtDlpRuntime(settings, client=client, run=Processes(), clock=clock)
    assert not again.update_due(3600)
    clock.advance(1800)
    assert again.update_due(3600)
    rt.state_file.write_text("{broken", encoding="utf-8")
    assert rt.last_check() is None


async def test_a_hung_update_times_out(tmp_path: Path) -> None:
    slow_settings = WorkerSettings(ytdlp_dir=tmp_path / "y", ytdlp_update_timeout_s=0.05)

    class Hanging(Processes):
        async def __call__(self, args: Sequence[str]) -> CompletedProcess[bytes]:
            await anyio.sleep(10)
            raise AssertionError("never")

    with pytest.raises(UpdateError, match="timed out"):
        await runtime(slow_settings, github(), Hanging()).update()
    assert list((tmp_path / "y" / "tmp").iterdir()) == []


async def test_updaters_use_private_tmp_dirs_and_sweep_stale_ones(
    settings: WorkerSettings,
) -> None:
    tmp_root = settings.ytdlp_dir / "tmp"
    busy = tmp_root / "2026.09.28-someone-else"
    stale = tmp_root / "2026.01.01-crashed"
    busy.mkdir(parents=True)
    stale.mkdir()
    os.utime(stale, (0, 0))
    await runtime(settings, github()).update()
    assert busy.is_dir()
    assert not stale.exists()
    assert sorted(p.name for p in tmp_root.iterdir()) == [busy.name]
