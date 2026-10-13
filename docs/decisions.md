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

## D9. Final audit: "go" for public exposure, after the edge and lockout fixes
- The final pre-production audit found no Critical or High issues. One Medium: strangers could lock a family member out of the public web sign-in, and password guessing could reach `/web/login` without Authelia.
- Decision: outside sign-in failures now cost a growing delay instead of a hard lock. The edge examples add a strict per-client rate limit on `POST /web/login`. Admin accounts may still sign in to the web player from outside: the admin panel itself stays LAN-only behind Authelia, and refusing admins would block their own listening.
- Also fixed: forged long `X-Forwarded-For` chains, IPv6 /64 buckets at the edge, ffmpeg restricted to the expected demuxers and codecs, "sign out every device", `noexec` `/tmp` for the api, HEAD never starts a download.
- Accepted residual risks, documented in SECURITY.md: the admin panel and the player share one origin (strict CSP, no XSS found); containers on the proxy network must be trusted; the public client address relies on Cloudflare's `X-Forwarded-For`.

## D10. QR connect through the phone's camera app, no scanning library
- The admin panel already shows a QR with `ultimatetunes://connect?url=…&key=…` (contracts/ids.md), but the app could not scan it. In-app scanning needs ML Kit (Google Play services, forbidden) or ZXing (a new dependency the author has not approved).
- Decision: the app handles the `ultimatetunes://connect` link, and the phone's camera app reads the QR and opens it. The app always asks for confirmation, showing the server address, before connecting or replacing a connection, so a malicious link cannot silently repoint the app.
- A link whose server does not answer, or is not UltimateTunes, never touches the current connection.
- Note (non-blocking): while a link's dialog is showing, further links are dropped and Connect waits again for 1 s, so the first link wins. A hostile app on the phone firing links faster than once a second can therefore keep the user's own confirmation from being accepted (a denial of service on that dialog), but it cannot get its own server accepted.

## D11. Outside password sign-in: availability traded for brute-force resistance
- An outsider who knows a username can keep that user's *password* sign-in from outside (web player login, key creation, password change) slowed to a crawl for as long as the attack lasts. Existing web sessions and API keys keep working, and LAN/Tailscale sign-in is unaffected.
- The alternative, no per-username brake, would allow fast password guessing from the Internet. Users who need password sign-in from outside under attack can use Tailscale or put Authelia in front of `/` and `/web`.
- The delay is reserved before the password hash is checked, so parallel requests cannot squeeze in extra guesses.
- The reservation is atomic within one api process (SQLite single writer). Several api replicas (phase 5, PostgreSQL/Redis) will need a row lock or compare-and-set in `reserve_backoff`.

## D12. First production candidate is 1.0.0-rc.1
- Everything planned for 1.0 is merged, but nothing has run in production yet and the signing passwords are not on the coordinator's machine, so the signed APK comes from the Release workflow (or from a local build by the author with the four `UT_*` variables). A release candidate lets the author install and deploy it, run the SECURITY.md author checklist (TLS, backup restore, limits through the real proxy, public client IPs in the audit log) and then cut 1.0.0 from the same code.
- versionCode 1000001; the final 1.0.0 will be 1000099.
