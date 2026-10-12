# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`ultimatetunes` command: one image, several roles and commands.

The commands come from the registry (`commands.py`): this module registers the coordinator's
own (`api`, `migrate`); areas register theirs in their own `cli.py` (e.g. `worker`, T08).
"""

import argparse
import logging
from collections.abc import Sequence

import uvicorn

from ultimatetunes import __version__
from ultimatetunes.commands import CommandRegistry, build_registry, no_args
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


def run_migrate(settings: Settings) -> int:
    conn = migrations.connect(settings.database_file)
    try:
        applied = migrations.migrate(conn, settings.migrations_dir)
    finally:
        conn.close()
    log.info("migrate: %d migration(s) applied: %s", len(applied), [m.name for m in applied])
    return 0


def register(registry: CommandRegistry) -> None:
    registry.add("api", no_args(run_api), help="Serve the api (OpenSubsonic, /ut/v1, internal)")
    registry.add("migrate", no_args(run_migrate), help="Apply the database migrations")


def main(argv: Sequence[str] | None = None, registry: CommandRegistry | None = None) -> int:
    registry = registry or build_registry()
    specs = registry.specs()
    parser = argparse.ArgumentParser(
        prog="ultimatetunes",
        description=__doc__,
        epilog="commands: " + "; ".join(f"{s.name}: {s.help}" for s in specs),
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("command", choices=[s.name for s in specs])
    parser.add_argument("args", nargs=argparse.REMAINDER, help="arguments of the command")
    parsed = parser.parse_args(argv)
    settings = Settings()
    configure_logging(settings.log_level)
    return registry.get(parsed.command).run(settings, parsed.args)
