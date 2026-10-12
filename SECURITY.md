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
| Compromised worker (yt-dlp runs untrusted extractor code paths) | No DB access, no inbound port, internal token scoped to job endpoints, separate volume for its updates | T08 |
| Container escape impact | Non-root, read-only root filesystem, dropped capabilities, no privileged mounts | T00, T22 |
| Vulnerable dependencies | Dependabot, pip-audit, Trivy, gitleaks in CI; nightly audit | T01 |
| Malicious audio/cover files | Files only produced by our own pipeline; mutagen/ffmpeg up to date; never execute content | T09 |
| Public exposure | Reverse proxy with TLS + HSTS + request limits; ZAP baseline scan | T22 |
| Future multi-replica deployment (k8s) | Shared state only through interfaces (Redis later), NetworkPolicies, PodSecurity restricted | Phase 5 |

## Notes for T22 (collected in Wave 1 reviews)
- **Admin allowlist trusts the TCP peer address.** Behind a reverse proxy, `tailscale serve` on the host, Tailscale Funnel or Docker's userland proxy, every client looks local or private. Public exposure needs a trusted-proxy rule (forwarded client IP from known proxies only) or a separate admin listener. The same applies to the client IP that password checks and the lockout use.
- **Admin logout is stateless**: it clears the signed cookie, but a copied cookie stays valid until it expires (default 8 h); a password change, disabling the user or a role change ends it at once. Options: a server-side revocation list or a shorter TTL. Without `UT_ADMIN_SESSION_SECRET` each process uses a random key.
- **Internal worker API on a separate listener** (or equivalent isolation) before any public exposure; in v1 it shares port 8044, reachable only over the internal Docker network.
- **`/readyz` detail**: decide what a public probe may reveal (database, schema, storage state); keep details internal.
- **Signing secrets** (if GitHub Actions return): keep the `UT_*` secrets in an environment limited to release tags, and check the APK signer certificate digest against a pinned value before publishing.
- **The api trusts the worker's SHA-256**: register compares the reported hash with the file at the path but does not hash the staging file itself, so a compromised worker could make it adopt an unowned file. Consider hashing on the api side.
- **Search cache and limits**: cap the size of the catalog cache (entries per kind, bytes) and add a per-user limit on external searches, so one user cannot fill `/data` or spend the shared 2 req/s catalog budget.

## Checklist before opening to the Internet (T22)
- [ ] All controls above implemented and tested.
- [ ] `/admin` reachable only from LAN/Tailscale (or explicitly opted in).
- [ ] TLS with a valid certificate; HSTS; HTTP → HTTPS.
- [ ] Rate limits verified from outside.
- [ ] No default or bootstrap credentials left.
- [ ] Image and dependency scans clean; ZAP baseline clean.
- [ ] Backups of `/data` tested by restoring them.
