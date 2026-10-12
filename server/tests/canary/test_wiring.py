# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The canary is wired in: the api's area hook and the worker command's factory."""

from typing import Any

import pytest

from ultimatetunes import app
from ultimatetunes.canary import web as canary_web
from ultimatetunes.canary.worker import build_canary_worker
from ultimatetunes.settings import Settings
from ultimatetunes.worker import cli as worker_cli
from ultimatetunes.worker import loop


def test_the_api_runs_the_canary_hook() -> None:
    assert canary_web in app.AREAS


def test_the_worker_command_builds_the_canary_worker(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def run_worker(given: Settings, **kwargs: Any) -> int:
        seen.update(kwargs, settings=given)
        return 0

    monkeypatch.setattr(loop, "run_worker", run_worker)
    assert worker_cli._worker(settings) == 0
    assert seen == {"settings": settings, "factory": build_canary_worker}
