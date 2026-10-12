<!--
SPDX-FileCopyrightText: 2026 UltimateTunes contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Decisions taken overnight (2026-10-12 → 2026-10-13)

A working log of the coordinator's decisions while the author was away; [SPEC.md §11](../SPEC.md#11-decisions) is the authoritative record and repeats the ones that shape the product.

The author asked to keep going overnight, release when appropriate, decide doubts and record them here.

## D1. Releases: prepared, tag push left to the author
- No signing passwords exist on the build machine (only the keystore files, which are never read), so a signed APK cannot be built locally.
- The repo is public, so the GitHub `Release` workflow (signed APK with the `UT_*` secrets + server image) costs nothing — but it is still disabled, and the repo's guard hook refuses version-tag pushes from the assistant by design.
- Decision: the coordinator prepares the release PR (`VERSION`, `CHANGELOG.md`, store changelogs) so `master` becomes release-ready; the author enables `Release` and pushes the tag (`git tag vX.Y.Z && git push origin vX.Y.Z`) when they want it published.

## D2. Cloudflare Tunnel is a supported edge, under conditions
- The audit said "never put a tunnel in front of the proxy" because tunnel traffic arrives from a private address. A common homelab setup is cloudflared → Traefik.
- Decision: supported when cloudflared and Traefik have pinned addresses on their network, Traefik trusts `X-Forwarded-For` only from cloudflared, the api's `UT_TRUSTED_PROXIES` lists exactly those two /32s, and `UT_ADMIN_ALLOWED_NETWORKS` excludes the Docker and tunnel ranges. An unpinned or untrusted tunnel stays unsupported. Documented in `deploy/traefik-cloudflared/` and `docs/architecture.md`.

## D3. Stale comments fixed as docs-only coordinator changes
- `contracts/openapi/internal-worker.yaml` now names the internal listener (`api:8045`); the `server/compose.yaml` header now says the worker leaves through `egress` and only the api calls YouTube Music. No contract behaviour changes.

## D4. Internal worker listener bound to the internal network only
- In shared-proxy deployments the api also joins the proxy's network, and the internal listener (8045) bound to `0.0.0.0` was reachable from every neighbour container, guarded only by the worker token.
- Decision: the deployment examples pin the api's address on `internal` and set `UT_INTERNAL_HOST` to it, so 8045 is reachable only from the internal network.

## D5. Authelia `trustForwardHeader: false` behind a tunnel
- cloudflared is the trusted peer for every Internet request, so trusting `X-Forwarded-Uri/Host` from it would let a tunnel client steer Authelia's bypass rules. The example sets `trustForwardHeader: false`.

## D6. Notification credentials only from env/Docker secrets, bound to one host
- The dependency set has no AEAD library, so ntfy/webhook credentials are never stored in the database (adding `cryptography` would need the author's approval). They come from `UT_NOTIFY_TOKEN` or `UT_NOTIFY_USERNAME`/`UT_NOTIFY_PASSWORD` (env or Docker secret).
- They are sent only when the target's host matches the operator-set `UT_NOTIFY_HOST`, so a stolen admin session cannot redirect them to another server by changing the notification URL.
- All settings classes hide input values in validation errors, so a refused secret never reaches a log.

## D7. Web player at `/`, built into the api
- The author asked for a complete web player at the home page. It is served by the api itself (no separate container), with Jinja + the vendored HTMX + a small own JS/CSS, no new dependencies, so it inherits every server limit and rule.
- Browsers sign in with username and password and get a signed `ut_web_session` cookie (HttpOnly, Secure, SameSite=Strict, per-user epoch so sign-out revokes copies); the API key never reaches the browser. Cookies use the admin session secret with separate salts, so admin and web cookies are not interchangeable.
- The old admin landing page at `/` was removed (no contract required it). `UT_WEB_ENABLED=false` turns the player off and `/` shows a plain "server is running" page.
- Playlist "move" rewrites the playlist through OpenSubsonic `createPlaylist` with `playlistId`, because OpenSubsonic has no move operation.

## D8. Android polish decisions (#70)
- One app-wide message area: above the mini player and tab bar, or at the top of the open full player, so feedback is never hidden.
- Tapping the open tab again returns to its first screen (other tabs keep their state).
- Dark launch window in dark mode (no white flash); light stays white.
- No extra R8/ProGuard rules were needed: a minified build was checked on the Pixel 8 (cold start 260 ms, 0.26 % janky frames in Library).
