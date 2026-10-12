# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`ultimatetunes canary`: one manual run (the GitHub job), with the fakes of the test stack.
No network and no real download: the real builders are only constructed, never called."""

import json
from pathlib import Path

import pytest

from ultimatetunes.canary import cli
from ultimatetunes.canary.settings import CanarySettings
from ultimatetunes.commands import build_registry
from ultimatetunes.core.clock import FakeClock
from ultimatetunes.search.catalog import CatalogThrottled
from ultimatetunes.search.fake import FakeMusicCatalog
from ultimatetunes.search.ytmusic import YTMusicCatalog
from ultimatetunes.settings import Settings
from ultimatetunes.worker.fake import FakeDownloader
from ultimatetunes.worker.ytdlp import YtDlpDownloader
from ultimatetunes.worker.ytdlp_runtime import YtDlpRuntime


def test_the_command_is_registered() -> None:
    assert build_registry().get("canary").run is cli.run_command


def test_a_green_run_prints_both_sides_and_exits_0(
    settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.run_command(settings, []) == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [(r["side"], r["ok"]) for r in lines] == [("catalog", True), ("download", True)]
    assert [c["name"] for c in lines[0]["checks"]] == ["search", "radio", "album", "playlist"]
    # The canary download never stays in staging.
    assert [p for p in settings.staging_dir.rglob("*") if p.is_file()] == []


@pytest.mark.parametrize("side", ["catalog", "download"])
def test_one_side_only(settings: Settings, capsys: pytest.CaptureFixture[str], side: str) -> None:
    assert cli.run_command(settings, ["--only", side]) == 0
    [line] = capsys.readouterr().out.splitlines()
    assert json.loads(line)["side"] == side


def test_a_failure_exits_1(
    settings: Settings, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def throttled(_settings: Settings) -> FakeMusicCatalog:
        catalog = FakeMusicCatalog()
        catalog.fail_with = CatalogThrottled()
        return catalog

    monkeypatch.setattr(cli, "build_catalog", throttled)
    assert cli.run_command(settings, ["--only", "catalog"]) == 1
    line = json.loads(capsys.readouterr().out)
    assert line["message"].startswith("search: YouTube Music is throttling requests")


def test_unknown_arguments_are_a_usage_error(settings: Settings) -> None:
    with pytest.raises(SystemExit):
        cli.run_command(settings, ["--only", "everything"])


@pytest.mark.anyio
async def test_run_canary_with_injected_builders(settings: Settings, clock: FakeClock) -> None:
    async def downloader(s: Settings) -> FakeDownloader:
        return await cli.build_downloader(s)  # type: ignore[return-value]

    reports = await cli.run_canary(
        settings, CanarySettings(), clock=clock, catalog=cli.build_catalog, downloader=downloader
    )
    assert [r.ran_at for r in reports] == ["2026-10-12T08:00:00.000Z"] * 2


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_the_real_catalog_is_bare_ytmusicapi(settings: Settings) -> None:
    real = settings.model_copy(update={"fake_youtube": False})
    assert isinstance(cli.build_catalog(real), YTMusicCatalog)


@pytest.mark.anyio
async def test_the_real_downloader_installs_yt_dlp_first(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    installed: list[bool] = []

    async def ensure_installed(self: YtDlpRuntime) -> str:
        installed.append(True)
        return "2026.09.28"

    monkeypatch.setattr(YtDlpRuntime, "ensure_installed", ensure_installed)
    monkeypatch.setenv("UT_YTDLP_DIR", str(tmp_path / "ytdlp"))
    real = settings.model_copy(update={"fake_youtube": False})
    assert isinstance(await cli.build_downloader(real), YtDlpDownloader)
    assert installed == [True]
