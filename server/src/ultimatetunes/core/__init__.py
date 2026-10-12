# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Cross-cutting interfaces shared by every stream, with their v1 implementations and fakes.

Owned by the coordinator (PLAN T02). Streams use them and never edit them; a change goes
through the coordinator. Module map:

- `clock`: `Clock` (`SystemClock`, `FakeClock`) and the timestamp format of the database.
- `cache`: `TtlCache` (`SqliteTtlCache` on `cache_entries`, `MemoryTtlCache` for tests).
- `ratelimit`: `RateLimiter` (`SqliteRateLimiter` on `rate_limit_buckets`): token bucket plus
  failure counter and lockout. Callers (auth in T04, the catalog in T06) choose the limits.
- `inflight`: `InFlight` (`MemoryInFlight`): single flight per key and listener counting.
- `storage`: `LibraryStore` / `StagingStore` confined to `/music` and `/staging`.
- `authn`: `Principal` and the `Authenticator` protocol that T04 implements in `auth/`.
- `services`: the `Services` container the app factory builds and handlers read.
- `netaddr`, `forwarded`: IP helpers and the client address behind trusted proxies (T22).
- `bodylimit`: the api-wide request body cap and `nosniff` (T22).
- `housekeeping`: periodic purge and size caps of the cache and the rate limiter (T22).

Interfaces owned by one stream live in that stream's package instead: `JobQueue` in `jobs/`
(T08), `MusicCatalog` in `search/` (T06), `Downloader` in `worker/` (T08), the UUIDv7
generator in `ids/` (T06). Errors are in `ultimatetunes.errors` (one mapping table).
"""
