<!--
SPDX-FileCopyrightText: 2026 UltimateTunes contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Errors

Every expected failure in the server is a subclass of `TunesError` (`server/src/ultimatetunes/errors.py`). **One mapping table**, the one below, turns each class into:
- an **OpenSubsonic error** (`/rest/*`): `subsonic-response.status = "failed"` with `error.code`, `error.message` and, where useful, `error.helpUrl`;
- an **RFC 9457 problem** (`/ut/v1/*` and `/internal/v1/*`): `Content-Type: application/problem+json` with `type`, `title`, `status`, `detail`, `instance` and our stable `code`.

Handlers raise typed errors. They never build envelopes or status codes by hand. Unexpected exceptions become `InternalError` and are logged with a correlation id, never with secrets.

## HTTP status on `/rest/*`

OpenSubsonic clients expect **HTTP 200** with a `failed` envelope, so every `/rest` error uses 200, except for:
- `RateLimited` → **429** with the envelope as body (code `0`) and `Retry-After`;
- `NotImplemented` → **501** with the envelope as body (code `0`). Only the T02 router stubs return it;
- `stream`/`download` with an unsatisfiable `Range` → **416** without a body (plain HTTP semantics, needed by players).

The envelope format follows `f` (`json` or `xml`, default `xml`). Binary endpoints (`stream`, `download`, `getCoverArt`) answer errors with the envelope in the requested format instead of the binary. If a download fails **after** the audio response has started (streaming while downloading), the server ends the chunked response early (no final zero-length chunk), so the client sees a broken transfer, never silent truncation passed off as success.

## Mapping

| `TunesError` subclass | When | OpenSubsonic code | HTTP (`/ut/v1`, `/internal/v1`) | Problem `code` |
| --- | --- | --- | --- | --- |
| `MissingParameter` | A required parameter is missing or empty | 10 | 400 | `missing_parameter` |
| `InvalidParameter` | A parameter has the wrong type, is out of range, or fails a format rule | 0 | 400 | `invalid_parameter` |
| `InvalidId` | An id fails the rules of `ids.md` | 70 | 400 | `invalid_id` |
| `ClientTooOld` | `v` is older than the oldest version we answer (1.0.0 is accepted, so in practice never) | 20 | — | — |
| `ServerTooOld` | `v` has a higher major version than ours (`1.16.1`) | 30 | — | — |
| `AuthenticationRequired` | No credentials at all | 10 | 401 | `authentication_required` |
| `AuthenticationFailed` | Wrong username or password (incl. the key-as-password path and `POST /ut/v1/keys`) | 40 | 401 | `authentication_failed` |
| `TokenAuthNotSupported` | `t`/`s` token authentication (we keep only Argon2id hashes) | 42 (see note) | — | — |
| `ConflictingAuth` | `apiKey` together with `u`, `p`, `t` or `s` (or `X-Api-Key` and `apiKey` with different values) | 43 | 400 | `conflicting_auth` |
| `InvalidApiKey` | Unknown, malformed or revoked API key | 44 | 401 | `invalid_api_key` |
| `AccountDisabled` | Valid credentials of a disabled user | 50 | 403 | `account_disabled` |
| `Forbidden` | Authenticated but not allowed (someone else's playlist, admin-only action) | 50 | 403 | `forbidden` |
| `NotFound` | No such artist, album, song, playlist, key, import, job, lyrics | 70 | 404 | `not_found` |
| `Conflict` | The request clashes with the current state (e.g. another track already at `libraryPath`). Repeating an idempotent action, such as revoking a key twice, is not a conflict | 0 | 409 | `conflict` |
| `FeatureDisabled` | Feature switched off in config (Spotify import without credentials) | 0 | 409 | `feature_disabled` |
| `UnsupportedUrl` | Import URL host not on the allowlist, or not a playlist URL | 0 | 400 | `unsupported_url` |
| `PayloadTooLarge` | Body or parameter list over the limit (e.g. more than 1,000 ids) | 0 | 413 | `payload_too_large` |
| `RateLimited` | Rate limit or temporary lockout (per IP, per key) | 0 (HTTP 429) | 429 | `rate_limited` |
| `UpstreamUnavailable` | YouTube Music, MusicBrainz, LRCLIB or Spotify failed or timed out | 0 | 502 | `upstream_unavailable` |
| `DownloadFailed` | The download job of the requested track failed for good | 0 | 502 | `download_failed` |
| `NotImplemented` | Router stub (T02) or a feature not built yet | 0 (HTTP 501) | 501 | `not_implemented` |
| `InternalError` | Anything unexpected | 0 | 500 | `internal_error` |
| **Internal worker API only** | | | | |
| `InvalidWorkerToken` | Missing or wrong `Authorization: Bearer` worker token | — | 401 | `invalid_worker_token` |
| `LeaseLost` | `leaseId` is not the job's current lease (expired and re-claimed, or never valid) | — | 409 | `lease_lost` |
| `InvalidStateTransition` | Transition not allowed by the job state machine (e.g. `progress` after `complete`) | — | 409 | `invalid_state_transition` |
| `PathRejected` | `libraryPath`/`stagingPath` escapes `/music` or `/staging`, or is not normalized | — | 422 | `path_rejected` |

Notes:
- **Error 42 vs 41.** SPEC RF-02, CLAUDE.md and SECURITY.md say token auth is refused with **42**. The OpenSubsonic API reference says servers that do not support token auth "**must** return error `41`" (whose text is about LDAP, but it "implies that Token authentication is not supported for _any_ reason"), and keeps `42` for other unsupported mechanisms. Clients are told to retry with another method on either code, so both work in practice. This contract follows SPEC (**42**) until the coordinator decides. Recorded as an open question.
- The `message` of `TokenAuthNotSupported` and `InvalidApiKey` carries a `helpUrl` pointing to the server's key page (`/admin/keys` for admins, the README section for users).
- `AuthenticationFailed`, `InvalidApiKey` and `AccountDisabled` count as failures for the rate limiter's lockout. Messages never reveal whether a username exists.
- `/ut/v1` problems use `type` = `https://github.com/qtekfun/UltimateTunes/blob/master/contracts/errors.md#<code>` and `title` = the English short text. `detail` is human-readable and may change. Clients switch on `code` only.
- `RateLimited` responses always carry `Retry-After` (seconds) on every API.
- Job failures are **not** HTTP errors on `/ut/v1/tracks/{id}/status`: that endpoint returns 200 with `state: failed` and an `error` object whose `code` is one of the worker error codes below.

## Worker error codes (`fail` → job `error.code`)

Reported by the worker in `POST /internal/v1/jobs/{jobId}/fail` and shown in `/ut/v1/tracks/{id}/status` and the admin panel.

| Code | Retryable | Meaning |
| --- | --- | --- |
| `video_unavailable` | no | Removed, private, region-blocked or age-gated video |
| `format_unavailable` | no | No Opus or M4A audio format offered |
| `extractor_error` | yes | yt-dlp failed to extract (often a YouTube change). Also alerts the admin |
| `network_error` | yes | Timeout or connection error while downloading |
| `rate_limited_upstream` | yes | YouTube throttled or blocked (HTTP 429/403) |
| `tagging_failed` | yes | mutagen or ffmpeg (ReplayGain) failed |
| `storage_error` | yes | Disk full or I/O error on `/staging` or `/music` |
| `cancelled` | no | Cancelled by an admin (the job ends in `cancelled`, not `failed`) |
| `lease_expired` | yes | Set by the api, never sent by a worker: the lease ran out (worker killed or hung) |
| `internal_error` | yes | Anything else |

Retryable failures go back to `queued` with exponential backoff (30 s, 2 min, 8 min, ±20 % jitter), up to `max_attempts` (3). After that, or for a non-retryable code, the job ends in `failed`.
