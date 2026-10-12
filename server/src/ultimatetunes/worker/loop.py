# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The worker main loop. Owner: PLAN T08 (claim jobs on the internal worker API, download,
tag, register, complete). Until then it idles until SIGTERM/SIGINT, which is the shutdown
path T08 keeps."""

import logging
import signal
import threading
from collections.abc import Callable
from types import FrameType

from ultimatetunes.settings import Settings
from ultimatetunes.worker.settings import WorkerSettings

log = logging.getLogger(__name__)

SignalInstaller = Callable[[int, Callable[[int, FrameType | None], None]], object]


def run_worker(
    settings: Settings,
    worker_settings: WorkerSettings | None = None,
    stop: threading.Event | None = None,
    install: SignalInstaller = signal.signal,
) -> int:
    worker_settings = worker_settings or WorkerSettings()
    stop = stop or threading.Event()

    def _on_signal(signum: int, _frame: FrameType | None) -> None:
        log.info("worker: signal %s received, stopping", signum)
        stop.set()

    install(signal.SIGTERM, _on_signal)
    install(signal.SIGINT, _on_signal)
    log.info("worker started (staging=%s, api=%s)", settings.staging_dir, worker_settings.api_url)
    while not stop.wait(timeout=5.0):
        pass
    log.info("worker stopped")
    return 0
