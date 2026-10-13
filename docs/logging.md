<!--
SPDX-FileCopyrightText: 2026 UltimateTunes contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Logging and security events

Both containers log **one JSON object per line on stdout** (12-factor; Docker keeps them with its
`json-file` driver, 10 MiB x 3 in `server/compose.yaml`). Every line goes through one redacting
handler (`server/src/ultimatetunes/logging.py`): API keys (`utk_…`), ntfy tokens, `Authorization`
values, cookies, and the values of `apiKey`, `p`, `t`, `s`, `password`, `token` and `secret` in
URLs, JSON or free text are replaced by `[REDACTED]` before anything is written, and a field
whose **name** looks like a secret is replaced whole. Tests: `tests/test_logging.py`,
`tests/core/test_security_log.py`, `tests/core/test_accesslog.py`, and every
`tests/*/test_security_events.py` renders its lines and checks that no password or key appears.

This page lists what a SIEM, CrowdSec or a log search can rely on: the access log and the
**security events**, with stable names and fields. Free-text messages may change between
versions; `event` names and their fields only change with a note in the changelog.

## Line format

Every line has:

| Key | What |
|---|---|
| `time` | ISO 8601 in UTC, e.g. `2026-10-13T09:18:47.254431+00:00` |
| `level` | `DEBUG`, `INFO`, `WARNING` or `ERROR` (`UT_LOG_LEVEL`) |
| `logger` | `ultimatetunes.access` (access log), `ultimatetunes.security` (security events), any other `ultimatetunes.*` module, `uvicorn.error` |
| `message` | Human-readable text (redacted) |

Access lines and security events add **flat fields at the top level**: `event` and the fields
below. A field is left out when it has no value. Strings that come from the client (usernames,
paths, user agents, query strings) are cut at 256 characters.

### The client address

`client_ip` is always the **resolved** client: the TCP peer, or, when the peer is in
`UT_TRUSTED_PROXIES`, the address that proxy put in `X-Forwarded-For` (read from the right,
`core/forwarded.py`). Behind `tailscale serve` that is the device's tailnet address; behind
the Traefik example it is the Internet client's address. `peer_ip` (access log only) is the TCP
peer itself. If `client_ip` shows the proxy's address (for example the Docker gateway) for every
request, `UT_TRUSTED_PROXIES` is not set correctly (`deploy/README.md`).

### Common fields of security events

Events raised while handling a request carry the request's `client_ip`, `surface`, `method` and
`path` (never the query string). `surface` is the part of the api:

| `surface` | Paths |
|---|---|
| `web` | `/`, `/web`, `/web/*` (web player) |
| `admin` | `/admin`, `/admin/*` (panel) |
| `subsonic` | `/rest/*` (OpenSubsonic) |
| `ut_keys` | `/ut/v1/keys` (password sign-in that creates a device key) |
| `ut` | any other `/ut/v1/*` |
| `internal` | `/internal/*` (worker API; on the client port it is always a 404) |
| `probe` | `/healthz`, `/readyz` |
| `other` | anything else (scanners) |

## Access log: `http.request`

Logger `ultimatetunes.access`, level `INFO`, one line per request on either listener, including
requests the listener refuses by itself (`/internal/*` on the client port). It replaces
uvicorn's own access log, which showed the proxy instead of the client and the full query string.

| Field | What |
|---|---|
| `client_ip` | Resolved client (above) |
| `peer_ip` | TCP peer |
| `method`, `path` | Request line; the path without the query string |
| `query` | The query string, redacted (`apiKey=[REDACTED]`) |
| `status` | Response status (500 when the app failed before answering) |
| `bytes` | Response body bytes sent |
| `duration_ms` | Until the response ended (a stream: its whole length) |
| `surface` | As above |
| `listener` | `client` (8044) or `internal` (8045) |
| `user_agent` | `User-Agent` header |
| `via_untrusted_proxy` | `true` when a peer outside `UT_TRUSTED_PROXIES` sent forwarding headers |

Example:

```json
{"time": "2026-10-13T09:20:01.120000+00:00", "level": "INFO", "logger": "ultimatetunes.access", "message": "100.64.7.8 \"GET /rest/ping.view\" 200", "event": "http.request", "client_ip": "100.64.7.8", "peer_ip": "10.213.46.1", "method": "GET", "path": "/rest/ping.view", "query": "f=json&apiKey=[REDACTED]", "status": 200, "bytes": 52, "duration_ms": 3.1, "surface": "subsonic", "listener": "client", "user_agent": "Feishin/1.0"}
```

## Security events

Logger `ultimatetunes.security`. Passwords, API keys, tokens, cookies and session values are
never fields; `user` is the username as typed (lower-cased), so a username field may hold
whatever a client sent.

| `event` | Level | When | Fields besides the common ones |
|---|---|---|---|
| `auth.failure` | WARNING | A credential was checked and refused, or a request to an authenticated endpoint had unusable credentials | `reason`, `credential`, `user`, `known_user`, `trusted`, `key_id` |
| `auth.throttled` | WARNING | Refused **before** checking: a lock, the outside delay of a username, a rate limit, or no free Argon2 slot | `reason`, `user`, `key_id`, `retry_after_s` |
| `auth.lockout` | WARNING | A failure counter reached its limit (also written to the audit log) | `scope`, `target`, `user`, `duration_s` |
| `auth.success` | INFO | A password sign-in succeeded (web, panel, `POST /ut/v1/keys`, password change check), or an API key was used from a new address or after a minute | `credential`, `user`, `user_id`, `key_id`, `trusted` |
| `access.denied` | WARNING | `/admin` refused a network, or a signed-in user is not an admin | `reason`, `user` |
| `csrf.failure` | WARNING | A state change of the panel or the web player, or a login form, without a valid CSRF token or from another site | `reason` |
| `session.rejected` | WARNING | A session cookie was sent but cannot be used | `reason`, `user` |
| `ratelimit.hit` | WARNING | Any answer with status 429 (auth limits, per-user request rate, search and catalog budgets, download limits) | `listener` |
| `audit` | INFO | Every audit-log entry, as it is written: sign-ins, sign-outs, users, keys, settings, deletions, lockouts | `action`, `user_id`, `target_type`, `target_id` (never the entry's `detail`) |

### `reason` values

| `event` | `reason` | Meaning |
|---|---|---|
| `auth.failure` | `bad_password` | Wrong password or unknown username (`known_user` tells them apart; the client never can) |
| | `invalid_key` | Unknown or malformed API key (`credential: api_key`) |
| | `bad_credentials` | OpenSubsonic `u` + `p` where `p` is not an API key of that user (`credential: subsonic_password`) |
| | `revoked_key` | A revoked key (a stale device; not counted toward lockouts) |
| | `account_disabled` | The user is disabled (key or password) |
| | `token_auth` | OpenSubsonic `t`/`s` token auth (refused by design, error 42) |
| | `conflicting_auth` | Two different credentials in one request |
| | `missing_credentials` | An authenticated endpoint without credentials |
| | `no_client_address` | A password check without a client address (misconfigured proxy) |
| `auth.throttled` | `ip_locked` | The client's address is locked after too many failures |
| | `user_locked` | The username is locked for sign-ins from the admin's networks |
| | `user_backoff` | The username's growing delay for sign-ins from outside is running |
| | `global_lock` | Too many failures from outside in the last minute (`UT_AUTH_MAX_FAILURES_GLOBAL_PER_MIN`) |
| | `login_rate` | The per-address password-check rate (`UT_AUTH_LOGIN_RATE_PER_S`) |
| | `key_rate` | The per-key request rate (`UT_AUTH_KEY_RATE_PER_S`) |
| | `argon2_busy` | No free Argon2 slot in time (`UT_AUTH_ARGON2_CONCURRENCY`) |
| `access.denied` | `network` | Client outside `UT_ADMIN_ALLOWED_NETWORKS` |
| | `worker_network` | Client in the worker's networks (`UT_WORKER_NETWORKS`) |
| | `untrusted_proxy` | Forwarding headers from a peer outside `UT_TRUSTED_PROXIES` |
| | `funnel` | A Tailscale Funnel request |
| | `not_admin` | A valid user who is not an admin (session or login form) |
| `csrf.failure` | `token` | Missing or wrong session CSRF token |
| | `login_token` | Missing, expired or wrong login-form token |
| | `cross_site` | `Sec-Fetch-Site` says another site |
| `session.rejected` | `invalid_or_expired` | Bad signature, garbage or expired cookie |
| | `unknown_user` | The cookie's user no longer exists |
| | `account_disabled` | The user is disabled |
| | `revoked` | Ended by a sign-out, a password change or "sign out every device" |

Other fields: `credential` is `password`, `api_key` or `subsonic_password`; `trusted` is true
when the request came from the admin's own networks (`core.forwarded.from_trusted_network`:
LAN/Tailscale, not through an untrusted proxy or Funnel), which picks the lockout counter;
`scope` of `auth.lockout` is `ip`, `user` (inside counter), `user-out` (outside counter: the
start of a long delay, not a lock) or `global`, and `target` the address (IPv6 by its /64) or
username.

Example (a wrong password on the web player through Traefik):

```json
{"time": "2026-10-13T09:21:13.004000+00:00", "level": "WARNING", "logger": "ultimatetunes.security", "message": "auth.failure (bad_password)", "event": "auth.failure", "client_ip": "203.0.113.7", "surface": "web", "method": "POST", "path": "/web/login", "reason": "bad_password", "user": "ana", "known_user": true, "trusted": false, "credential": "password"}
```

### What is not logged

- Successful requests with an API key, one by one: the access log has every request, and
  `auth.success` with `credential: api_key` shows each key's use at most once a minute per
  address (when its `last_used_at` is written).
- The query string's credentials, request bodies, cookies and headers other than `User-Agent`.
- The `detail` of audit entries (it stays in the database, visible in the panel's audit page).
- The worker logs its own work (downloads, yt-dlp updates, canary) but has no users and no
  security events; its lines never reach the client's address.

## Using the events

- **CrowdSec**: acquire the api container's logs (docker data source, container
  `ultimatetunes-api-1` with the Compose project name `ultimatetunes`), parse the JSON, and
  bucket `auth.failure` with the guessing reasons (`bad_password`, `invalid_key`,
  `bad_credentials`) per `client_ip`; `access.denied` and 404s under `/admin` or `/internal` are
  probes. Whitelist your LAN and tailnet so a typo at home never bans your own devices.
- **Behind a proxy**, check once that `client_ip` shows real clients (tailnet addresses behind
  `tailscale serve`, public ones behind Traefik), never the proxy's address.
- The audit log in the database is the durable record; the log is the stream. Keep the
  container logs as long as your analysis needs (`json-file` rotates at 30 MiB by default).
- **Cardinality**: `user`, `path` and `user_agent` are client-controlled and clipped to 256
  characters but otherwise unbounded in distinct values, so a spray from many usernames, paths
  or agents inflates index cardinality and volume by about one access line plus one event per
  request. The per-IP rate limits and the clip bound it; size the SIEM index for it and alert on
  the rate of `auth.failure`/`access.denied` rather than keeping every distinct value hot.
