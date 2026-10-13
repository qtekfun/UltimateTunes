# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`ultimatetunes` command: one image, several roles and commands.

The commands come from the registry (`commands.py`): this module registers the coordinator's
own (`api`, `migrate`); areas register theirs in their own `cli.py` (e.g. `worker`, T08).
"""

import argparse
import asyncio
import logging
from collections.abc import Sequence
from typing import Any

import uvicorn

from ultimatetunes import __version__, listeners
from ultimatetunes.commands import CommandRegistry, build_registry, no_args
from ultimatetunes.db import migrate as migrations
from ultimatetunes.logging import configure_logging
from ultimatetunes.settings import Settings

log = logging.getLogger("ultimatetunes")


def run_api(settings: Settings) -> int:
    """Serves the api on its two listeners (`listeners.py`): clients on `UT_PORT`, the internal
    worker API on `UT_INTERNAL_PORT`. uvicorn stops gracefully on SIGTERM within the shutdown
    timeout."""
    from ultimatetunes.app import create_app  # noqa: PLC0415 - only the api role needs FastAPI
    from ultimatetunes.core.accesslog import AccessLog  # noqa: PLC0415 - same

    if settings.internal_port == settings.port:
        raise SystemExit("UT_INTERNAL_PORT must differ from UT_PORT")
    app = create_app(settings)
    common: dict[str, Any] = {
        "log_config": None,
        # Client addresses behind a proxy come from `core/forwarded.py` (UT_TRUSTED_PROXIES).
        "proxy_headers": False,
        # `core/accesslog.py` logs every request with the resolved client address instead.
        "access_log": False,
        "server_header": False,
        "timeout_graceful_shutdown": settings.shutdown_timeout_s,
        # Slow and idle connections (audit M2); no header timeout exists in uvicorn, so a
        # public deployment keeps Caddy in front (deploy/README.md).
        "http": "h11",
        "timeout_keep_alive": settings.keepalive_timeout_s,
        "backlog": settings.backlog,
        "h11_max_incomplete_event_size": settings.max_header_bytes,
    }
    proxies = settings.proxy_networks
    client = uvicorn.Config(
        AccessLog(listeners.Listener(app, internal=False), proxies=proxies, listener="client"),
        host=settings.host,
        port=settings.port,
        lifespan="on",
        limit_concurrency=settings.limit_concurrency,
        **common,
    )
    internal = uvicorn.Config(
        AccessLog(listeners.Listener(app, internal=True), proxies=proxies, listener="internal"),
        host=settings.internal_bind,
        port=settings.internal_port,
        lifespan="off",
        limit_concurrency=settings.internal_limit_concurrency,
        **common,
    )
    asyncio.run(listeners.serve(client, internal))
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
    registry.add(
        "api",
        no_args(run_api),
        help="Serve the api (OpenSubsonic, /ut/v1, admin; internal API on its own port)",
    )
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
