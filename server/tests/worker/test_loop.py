# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The worker role: its command, its settings and the SIGTERM shutdown path."""

import signal
import threading
from collections.abc import Callable
from types import FrameType

import pytest

from ultimatetunes.commands import CommandRegistry
from ultimatetunes.settings import Settings
from ultimatetunes.worker import cli as worker_cli
from ultimatetunes.worker import loop
from ultimatetunes.worker.settings import WorkerSettings

Handler = Callable[[int, FrameType | None], None]


def test_worker_stops_on_sigterm(settings: Settings) -> None:
    handlers: dict[int, Handler] = {}

    def install(signum: int, handler: Handler) -> None:
        handlers[signum] = handler

    stop = threading.Event()
    thread = threading.Thread(
        target=loop.run_worker, args=(settings, WorkerSettings(), stop, install)
    )
    thread.start()
    while signal.SIGTERM not in handlers:
        thread.join(timeout=0.01)
    handlers[signal.SIGTERM](signal.SIGTERM, None)
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert signal.SIGINT in handlers


def test_worker_command_runs_the_loop(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Settings] = []

    def run_stub(s: Settings) -> int:
        seen.append(s)
        return 0

    monkeypatch.setattr(loop, "run_worker", run_stub)
    registry = CommandRegistry()
    worker_cli.register(registry)
    assert registry.get("worker").run(settings, []) == 0
    assert seen == [settings]


def test_worker_settings_come_from_ut_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    assert WorkerSettings().api_url == "http://api:8044"
    monkeypatch.setenv("UT_API_URL", "http://api.internal:8044")
    monkeypatch.setenv("UT_WORKER_ID", "worker-1")
    configured = WorkerSettings()
    assert (configured.api_url, configured.worker_id) == ("http://api.internal:8044", "worker-1")
