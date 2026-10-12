# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`ultimatetunes` command: one image, several roles (api, worker, migrate)."""

import argparse
import logging
import signal
import threading
from collections.abc import Callable, Sequence
from types import FrameType

import uvicorn

from ultimatetunes import __version__
from ultimatetunes.db import migrate as migrations
from ultimatetunes.logging import configure_logging
from ultimatetunes.settings import Settings

log = logging.getLogger("ultimatetunes")


def run_api(settings: Settings) -> int:
    """Serves the api. uvicorn stops gracefully on SIGTERM within the shutdown timeout."""
    from ultimatetunes.app import create_app  # noqa: PLC0415 - only the api role needs FastAPI

    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_config=None,
        proxy_headers=False,
        server_header=False,
        timeout_graceful_shutdown=settings.shutdown_timeout_s,
    )
    return 0


def run_worker(
    settings: Settings,
    stop: threading.Event | None = None,
    install: Callable[[int, Callable[[int, FrameType | None], None]], object] = signal.signal,
) -> int:
    """Worker loop. Claiming and running download jobs comes in PLAN T08; for now it idles
    until SIGTERM/SIGINT, which is the shutdown path T08 keeps."""
    stop = stop or threading.Event()

    def _on_signal(signum: int, _frame: FrameType | None) -> None:
        log.info("worker: signal %s received, stopping", signum)
        stop.set()

    install(signal.SIGTERM, _on_signal)
    install(signal.SIGINT, _on_signal)
    log.info("worker started (staging=%s)", settings.staging_dir)
    while not stop.wait(timeout=5.0):
        pass
    log.info("worker stopped")
    return 0


def run_migrate(settings: Settings) -> int:
    conn = migrations.connect(settings.database_file)
    try:
        applied = migrations.migrate(conn, settings.migrations_dir)
    finally:
        conn.close()
    log.info("migrate: %d migration(s) applied: %s", len(applied), [m.name for m in applied])
    return 0


ROLES: dict[str, Callable[[Settings], int]] = {
    "api": run_api,
    "worker": run_worker,
    "migrate": run_migrate,
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ultimatetunes", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("role", choices=sorted(ROLES))
    args = parser.parse_args(argv)
    settings = Settings()
    configure_logging(settings.log_level)
    return ROLES[args.role](settings)
