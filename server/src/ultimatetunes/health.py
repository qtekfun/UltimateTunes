# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Liveness and readiness probes (Docker healthcheck now, Kubernetes probes later)."""

import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, Request, Response, status

from ultimatetunes.core.forwarded import via_untrusted_proxy
from ultimatetunes.core.netaddr import LOOPBACK, IpNetwork, in_networks
from ultimatetunes.db import DatabaseError, migrate
from ultimatetunes.db.driver import connect_sqlite
from ultimatetunes.settings import Settings

log = logging.getLogger(__name__)
router = APIRouter()
# `app.state` attribute: the networks that may read the `/readyz` detail.
PROBE_NETWORKS_STATE = "probe_networks"


@router.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    """The process answers. No dependency is checked here."""
    return {"status": "ok"}


@router.get("/readyz", include_in_schema=False)
def readyz(request: Request, response: Response) -> dict[str, object]:
    """Database reachable, schema up to date, library and staging writable.

    The status code and `status` are for everyone (probes, a proxy's health check); the
    per-check detail only for callers inside `PROBE_NETWORKS_STATE` (loopback, plus the admin
    allowlist once the admin area is installed) that did not come through an untrusted proxy
    and are not on the worker's network (`UT_WORKER_NETWORKS`).
    """
    settings: Settings = request.app.state.settings
    checks = {
        "database": _check_database(settings),
        "music": _check_writable(settings.music_dir),
        "staging": _check_writable(settings.staging_dir),
    }
    ready = all(result == "ok" for result in checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    body: dict[str, object] = {"status": "ok" if ready else "unavailable"}
    if _may_see_detail(request):
        body["checks"] = checks
    return body


def _may_see_detail(request: Request) -> bool:
    networks: tuple[IpNetwork, ...] = getattr(request.app.state, PROBE_NETWORKS_STATE, LOOPBACK)
    host = request.client.host if request.client else None
    settings: Settings = request.app.state.settings
    return (
        not via_untrusted_proxy(request.scope)
        and in_networks(host, networks)
        and not in_networks(host, settings.worker_network_list)
    )


def _check_database(settings: Settings) -> str:
    if not settings.database_file.is_file():
        return "missing"
    try:
        conn = connect_sqlite(settings.database_file, read_only=True)
        try:
            todo = migrate.pending(conn, settings.migrations_dir)
        finally:
            conn.close()
    except (DatabaseError, OSError, ValueError) as exc:
        log.warning("readiness: database check failed: %s", exc)
        return "error"
    return "ok" if not todo else "migrations pending"


def _check_writable(directory: Path) -> str:
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".readyz-"):
            pass
    except OSError:
        return "not writable"
    return "ok"
