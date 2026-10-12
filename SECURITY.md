<!--
SPDX-FileCopyrightText: 2026 UltimateTunes contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Security

UltimateTunes runs on your network and, eventually, on the Internet. Security is a requirement, not a phase. This file is the threat model and the checklist the `independent-reviewer` agent walks in PLAN T22.

## Reporting
Private report through GitHub's "Report a vulnerability" (Security tab). Please do not open public issues for vulnerabilities.

## Assets
Music library, user accounts, API keys, admin panel, the host running the containers, the YouTube session (if cookies are ever configured).

## Threats and controls

| Threat | Control | Task |
|---|---|---|
| Stolen or guessed credentials | API keys (256-bit, hashed, per device, revocable), Argon2id passwords, rate limit + lockout per IP and key, audit log | T04 |
| OpenSubsonic token auth needs reversible passwords | Refused (`t`/`s` → error 42); keys only | T04 |
| Credentials leaking in logs or URLs | Redacting log filter with tests; no keys in log lines; HTTPS only | T00, T04 |
| Command injection through yt-dlp/ffmpeg | Argument lists only, ids validated (`^[A-Za-z0-9_-]{11}$`), no shell | T08, T09 |
| Path traversal from metadata | Path sanitizer (100 % coverage), storage interfaces confined to `/music` and `/staging` | T09 |
| SSRF through imports or covers | Host allowlist for import URLs; covers only from Cover Art Archive / YouTube image hosts | T09, T11 |
| Admin panel abuse | Admin role, CSRF tokens, `SameSite=Strict` cookies, LAN/Tailscale allowlist by default | T15 |
| Compromised worker (yt-dlp runs untrusted extractor code paths) | No DB access, no inbound port, internal token scoped to job endpoints on their own listener (8045, never published), the api re-hashes registered files, separate volume for its updates | T08, T22 |
| Container escape impact | Non-root, read-only root filesystem, dropped capabilities, `no-new-privileges`, PID limit, no privileged mounts | T00, T22 |
| Vulnerable dependencies | Dependabot, pip-audit, Trivy, gitleaks in CI; nightly audit | T01 |
| Malicious audio/cover files | Files only produced by our own pipeline; mutagen/ffmpeg up to date; never execute content | T09 |
| Public exposure | Reverse proxy with TLS + HSTS + request limits (`deploy/caddy/`), client address only from trusted proxies, `/readyz` detail internal; ZAP baseline scan (`tools/zap-baseline.sh`) | T22 |
| Resource exhaustion by one user | Per-user limit on external searches, capped and purged search cache, purged rate-limit state | T22 |
| Future multi-replica deployment (k8s) | Shared state only through interfaces (Redis later), NetworkPolicies, PodSecurity restricted | Phase 5 |

## Notes for T22 (collected in Wave 1 reviews) and what T22 did
- **Admin allowlist trusted the TCP peer address.** Done: `core/forwarded.py` is the outermost middleware and decides the client address for everything (admin allowlist, `/readyz`, per-IP limits and lockout, audit log). `X-Forwarded-For` is read only from peers in `UT_TRUSTED_PROXIES` (from the right, skipping trusted hops); with the default (empty), a request that carries forwarding headers is refused by `/admin` (403), and a Tailscale Funnel request (`Tailscale-Funnel-Request`) always is. `tailscale serve` and Caddy add `X-Forwarded-For`, so behind them the admin sets `UT_TRUSTED_PROXIES` to the Docker bridge gateway (`deploy/README.md`). Tests: `tests/core/test_forwarded.py`, `tests/admin/test_proxies_and_logout.py`.
- **Admin logout was stateless.** Done: each admin has a session epoch (row `admin.session_epoch.<user id>` in `settings`) mixed into the cookie fingerprint; logout bumps it, so every copy of that admin's session cookie stops working at once (other admins are untouched). Without `UT_ADMIN_SESSION_SECRET` each process still uses a random key (logged as a warning); `server/compose.yaml` sets it as a Docker secret.
- **Internal worker API on a separate listener.** Done: the api serves one app on two ports (`listeners.py`): clients on 8044, `/internal/v1` only on 8045 (`UT_INTERNAL_PORT`), which compose never publishes; the client port answers a plain 404 for `/internal/*`. The worker uses `UT_API_URL=http://api:8045`. On shutdown the client listener stops accepting, waits for the internal one to drain, and only then ends the lifespan (which closes the database). In `server/compose.yaml` the worker shares only the pinned `internal` network with the api (its way out is its own `egress` network), and the api refuses `/admin` and the `/readyz` detail to that subnet (`UT_WORKER_NETWORKS`, from `UT_INTERNAL_SUBNET`, default `10.213.44.0/24`). The test stack does not pin it (several test stacks run at once), so there the worker could still load the panel's login form: residual, test-only. Tests: `tests/test_listeners.py`, `tests/admin/test_proxies_and_logout.py`.
- **`/readyz` detail.** Done: everyone gets the status code and `{"status": ...}`; the per-check detail only goes to loopback and the admin allowlist, never through an untrusted proxy nor to the worker's network (`tests/test_health.py`).
- **Signing secrets** (if GitHub Actions return): still open, for when releases are published (RELEASING.md); nothing is published while publishing is paused.
- **The api trusted the worker's SHA-256.** Done: `registerTrack` hashes the staging file itself, once and before taking the write lock (lease and path checked first, size checked again inside the transaction), and refuses a mismatch (`409 conflict`), so a worker cannot make it adopt a file by reporting that file's hash (`tests/register/test_register.py`). The worker still mounts `/music` read-write to move files (by design, T08); the ReplayGain report's hash of an album-gain rewrite is still the worker's.
- **Search cache and limits.** Done: a per-user bucket of external searches, charged by both `search3` and `/ut/v1/search` (`UT_SEARCH_USER_RATE_PER_S` 0.2/s, `UT_SEARCH_USER_BURST` 20; past it, search is library-only, never an error), and api housekeeping every 10 min (`core/housekeeping.py`): expired cache entries removed, the cache trimmed to `UT_CACHE_MAX_ENTRIES` (200 000) and `UT_CACHE_MAX_BYTES` (256 MiB) oldest first, idle rate-limit buckets forgotten. Neither table was ever purged before.
- **Found during T22:** httpx logged every outbound request URL at INFO, which put the ntfy topic (a secret) and webhook paths in the logs; `httpx`/`httpcore` now log from WARNING up (`tests/test_logging.py`). The panel and landing page also send `Permissions-Policy` and `Cross-Origin-Embedder-Policy`, and every answer `X-Content-Type-Options: nosniff` (ZAP baseline). Request bodies are capped api-wide (`UT_MAX_BODY_BYTES`, 4 MiB; `core/bodylimit.py`; a declared or chunked body past it gets a 413 problem, never reaching the app), since `tailscale serve` has no limit of its own.

## Checklist before opening to the Internet (T22)
Evidence for each item; the ones marked *author* depend on the homelab and are done there, not in this repository (nothing is deployed or published by the project).
- [x] All controls above implemented and tested. Every row of the table has tests in `server/tests` (`make -C server check`: ruff, mypy strict, pytest with 100 % on the critical modules, bandit, pip-audit, forbidden dependencies); the T22 notes above are closed except release signing, which waits for publishing.
- [x] `/admin` reachable only from LAN/Tailscale (or explicitly opted in). Default `UT_ADMIN_ALLOWED_NETWORKS`, client address from trusted proxies only, forwarded/Funnel requests refused; `deploy/caddy/Caddyfile` refuses `/admin` from outside private and Tailscale ranges too.
- [ ] TLS with a valid certificate; HSTS; HTTP → HTTPS. *Author*: `tailscale serve` (`deploy/tailscale/README.md`) gives HTTPS inside the tailnet; for public access, Caddy (`deploy/caddy/Caddyfile`: automatic certificate, HTTP → HTTPS redirect, HSTS one year).
- [ ] Rate limits verified from outside. Verified against the local test stack (repeated wrong keys get error 44 then a lockout, see the T22 PR); *author*: repeat through the real proxy once `UT_TRUSTED_PROXIES` is set, so the limits key on the real client.
- [x] No default or bootstrap credentials left. `bootstrap-admin` has no default password (env, Docker secret or terminal only); compose requires the worker token and session secret as Docker secrets; the only fixed token is the test stack's, documented as worthless.
- [x] Image and dependency scans clean; ZAP baseline clean. `pip-audit` and Trivy (CRITICAL/HIGH, `tools/ci-local.sh docker`) clean; `tools/zap-baseline.sh` (ZAP 2.17.0, pinned digest) clean against the test stack: no FAIL or WARN, informational rules ignored with their reasons in `tools/zap/baseline.conf`. Manual GitHub job: `.github/workflows/zap.yml`.
- [ ] Backups of `/data` tested by restoring them. *Author*: procedure in `deploy/README.md` (online SQLite backup, restore into a throwaway volume, `migrate`, `integrity_check`).
