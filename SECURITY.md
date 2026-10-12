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

## Checklist before opening to the Internet (T22)
- [ ] All controls above implemented and tested.
- [ ] `/admin` reachable only from LAN/Tailscale (or explicitly opted in).
- [ ] TLS with a valid certificate; HSTS; HTTP → HTTPS.
- [ ] Rate limits verified from outside.
- [ ] No default or bootstrap credentials left.
- [ ] Image and dependency scans clean; ZAP baseline clean.
- [ ] Backups of `/data` tested by restoring them.
