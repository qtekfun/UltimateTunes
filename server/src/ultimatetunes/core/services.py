# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`Services`: every shared dependency of the api, built once by the app factory.

Handlers read it from `request.app.state.services` (or `services(request)`); tests build their
own with fakes. Nothing here opens a connection or touches the disk until first use, so the
app starts (and `/healthz` answers) even without a database.
"""

from dataclasses import dataclass

from starlette.requests import HTTPConnection

from ultimatetunes.core.authn import Authenticator
from ultimatetunes.core.cache import SqliteTtlCache, TtlCache
from ultimatetunes.core.clock import Clock, SystemClock
from ultimatetunes.core.inflight import InFlight, MemoryInFlight
from ultimatetunes.core.limits import DownloadLimits
from ultimatetunes.core.ratelimit import RateLimiter, SqliteRateLimiter
from ultimatetunes.core.storage import (
    LibraryStore,
    LocalLibraryStore,
    LocalStagingStore,
    StagingStore,
)
from ultimatetunes.db.database import Database
from ultimatetunes.jobs.gate import DownloadGate
from ultimatetunes.jobs.queue import JobQueue, SqliteJobQueue
from ultimatetunes.search.catalog import MusicCatalog, build_catalog
from ultimatetunes.settings import Settings


@dataclass
class Services:
    settings: Settings
    clock: Clock
    db: Database
    cache: TtlCache
    rate_limiter: RateLimiter
    inflight: InFlight
    library: LibraryStore
    staging: StagingStore
    catalog: MusicCatalog
    jobs: JobQueue
    authenticator: Authenticator


def build_services(settings: Settings, clock: Clock | None = None) -> Services:
    from ultimatetunes.auth import PendingAuthenticator, build_authenticator  # noqa: PLC0415

    clock = clock or SystemClock()
    db = Database.sqlite(settings.database_file)
    cache = SqliteTtlCache(db, clock)
    rate_limiter = SqliteRateLimiter(db, clock)
    inflight = MemoryInFlight()
    library = LocalLibraryStore(settings.music_dir)
    staging = LocalStagingStore(settings.staging_dir)
    gate = DownloadGate(DownloadLimits(), clock, (library, staging))
    services = Services(
        settings=settings,
        clock=clock,
        db=db,
        cache=cache,
        rate_limiter=rate_limiter,
        inflight=inflight,
        library=library,
        staging=staging,
        # One database handle and one single-flight registry for the whole api.
        catalog=build_catalog(settings, cache=cache, limiter=rate_limiter, inflight=inflight),
        jobs=SqliteJobQueue(db, clock, gate=gate),
        authenticator=PendingAuthenticator(),
    )
    services.authenticator = build_authenticator(services)
    return services


def services(conn: HTTPConnection) -> Services:
    """The `Services` of the app serving this request (usable as a FastAPI dependency)."""
    found: Services = conn.app.state.services
    return found
