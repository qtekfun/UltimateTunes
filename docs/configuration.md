<!--
SPDX-FileCopyrightText: 2026 UltimateTunes contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Configuration reference

Everything the server reads is an environment variable starting with `UT_` (12-factor: no config files, nothing stored in the container). The api and the worker run from the same image and read the same names; the **Container** column says which of them uses each one.

- **Secrets** (`UT_WORKER_TOKEN`, `UT_ADMIN_SESSION_SECRET`, `UT_BOOTSTRAP_ADMIN_PASSWORD`, `UT_NOTIFY_TOKEN`, `UT_NOTIFY_USERNAME`, `UT_NOTIFY_PASSWORD`) can also be Docker secrets: a file named after the variable in lower case, prefix included, in `/run/secrets/` (for example `/run/secrets/ut_worker_token`). [`server/compose.yaml`](../server/compose.yaml) mounts them that way. Never put secrets in `.env` files you commit.
- **Booleans** accept `true`/`false` (also `1`/`0`, `yes`/`no`). **Sizes** are in bytes, **durations** in the unit the name ends with (`_S` seconds, `_H` hours, `_DAYS` days).
- A value out of its allowed range stops the container at start with a validation error naming the variable.
- Unknown `UT_*` variables are ignored, so a typo does not fail: check the name against this table.
- The admin panel shows the limits that matter day to day (download caps per user, free-space minimum); everything else is only visible here and in the logs.

This table is checked by a test (`server/tests/tools/test_configuration_doc.py`) against the settings classes of the code: a setting that is added, renamed or whose default changes fails CI until this page is updated. The test can print the missing rows: `cd server && uv run python -m tests.tools.test_configuration_doc`.

The admin's own guide is [admin-guide.md](admin-guide.md); deployment examples are in [deploy/README.md](../deploy/README.md).

## Paths, listeners and shared settings

| Setting | Default | Container | Meaning |
|---|---|---|---|
| `UT_DATA_DIR` | `/data` | api | Volume with the SQLite database and the cover cache. Back it up (deploy/README.md). |
| `UT_MUSIC_DIR` | `/music` | api, worker | The library: plain audio files in `Artist/Album/NN - Title.ext`. The api serves and scans it; the worker moves finished downloads into it. |
| `UT_STAGING_DIR` | `/staging` | api, worker | Partial downloads, one directory per job, shared by both containers (the api streams from it while the worker writes). |
| `UT_MIGRATIONS_DIR` | `/app/migrations` | api | Where the SQL migrations ship inside the image (`ultimatetunes migrate`). |
| `UT_DATABASE_PATH` | (unset) | api | Full path of the database file; unset means `UT_DATA_DIR/ultimatetunes.db`. |
| `UT_HOST` | `127.0.0.1` | api | Address the client listener binds to. The image sets `0.0.0.0`; compose decides what is published (`UT_BIND`). |
| `UT_PORT` | `8044` | api | Port of the client listener (OpenSubsonic, `/ut/v1`, `/admin`, `/web`). |
| `UT_INTERNAL_HOST` | (unset) | api | Address of the internal worker API listener; unset means `UT_HOST`. |
| `UT_INTERNAL_PORT` | `8045` | api | Port of the internal worker API (`/internal/v1`). It serves nothing else; never publish it. |
| `UT_TRUSTED_PROXIES` | (empty) | api | Comma-separated CIDRs of reverse proxies whose `X-Forwarded-For` is believed (the single bridge gateway behind `tailscale serve` or Caddy). Empty: no proxy is trusted and `/admin` refuses proxied requests. |
| `UT_WORKER_NETWORKS` | (empty) | api | Comma-separated CIDRs of the worker's networks; callers from there never get `/admin` or the `/readyz` detail. Compose fills it from `UT_INTERNAL_SUBNET` and `UT_EGRESS_SUBNET`. |
| `UT_MAX_BODY_BYTES` | `4194304` | api | Largest request body the api reads (4 MiB; an import file is at most 1 MiB). Minimum 64 KiB. |
| `UT_HOUSEKEEPING_INTERVAL_S` | `600` | api | How often expired cache entries and idle rate-limit buckets are purged and the cache caps applied. |
| `UT_CACHE_MAX_ENTRIES` | `200000` | api | Cap of the shared catalog cache in entries; the oldest go first. |
| `UT_CACHE_MAX_BYTES` | `268435456` | api | Cap of the shared catalog cache in bytes (256 MiB); the oldest go first. |
| `UT_LIMIT_CONCURRENCY` | `128` | api | Open connections or running requests of the client listener; past it uvicorn answers 503. Streams hold a connection while they play. |
| `UT_INTERNAL_LIMIT_CONCURRENCY` | `32` | api | The same cap for the internal worker API listener. |
| `UT_KEEPALIVE_TIMEOUT_S` | `5` | api | Idle keep-alive connections are closed after this many seconds. |
| `UT_BACKLOG` | `256` | api | Pending connections the kernel queues before refusing. |
| `UT_MAX_HEADER_BYTES` | `16384` | api | Largest request line plus headers (bytes). |
| `UT_LOG_LEVEL` | `INFO` | api, worker | `DEBUG`, `INFO`, `WARNING` or `ERROR`. Logs are JSON on stdout; secrets are always redacted. The access log (`INFO`) and the security events (`INFO` and `WARNING`) are listed in [logging.md](logging.md); `WARNING` keeps the security warnings but drops the access log and successful sign-ins. |
| `UT_SHUTDOWN_TIMEOUT_S` | `10` | api | Grace period for open requests on SIGTERM before the api stops. |
| `UT_WORKER_TOKEN` | (unset) | api, worker | Shared secret of the internal worker API, 32 characters or more (`openssl rand -hex 32`). Unset: the internal API refuses everyone and nothing downloads. Prefer the Docker secret. |
| `UT_FAKE_YOUTUBE` | `false` | api, worker | Test stack only: a fake catalog and a fake downloader instead of YouTube Music. Never in production. |

## Admin panel and accounts

| Setting | Default | Container | Meaning |
|---|---|---|---|
| `UT_ADMIN_SESSION_SECRET` | (unset) | api | Key that signs admin session cookies, 32 characters or more. Every api replica needs the same one. Unset: a random key per start (sessions end on every restart) and a warning in the log. Prefer the Docker secret. |
| `UT_ADMIN_SESSION_TTL_S` | `28800` | api | Lifetime of an admin session (8 hours); between 60 seconds and 7 days. |
| `UT_ADMIN_ALLOWED_NETWORKS` | `127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,169.254.0.0/16,fc00::/7,fe80::/10,100.64.0.0/10,fd7a:115c:a1e0::/48` | api | Comma-separated CIDRs allowed to reach `/admin` (loopback, private LAN ranges, link-local and Tailscale). Anything else gets 403 before any other check. Narrow it to your tailnet and your LAN's /24 (deploy/README.md). `0.0.0.0/0,::/0` opts in to access from anywhere. |
| `UT_ADMIN_PUBLIC_URL` | (unset) | api | The https address the app should use, prefilled in the new-key form (for example `https://music.example.com`). Unset: the address the browser used, when it is https. |
| `UT_ADMIN_NOTIFY_INTERVAL_S` | `60` | api | How often failed downloads, failed canary runs and low disk space are checked for notifications (the target is set in the panel). |
| `UT_NOTIFY_TOKEN` | (unset) | api | ntfy access token for a notification server that requires login, sent as `Authorization: Bearer`. Either this or `UT_NOTIFY_USERNAME` + `UT_NOTIFY_PASSWORD`, never both; needs `UT_NOTIFY_HOST`. Prefer the Docker secret. Never entered in the panel. |
| `UT_NOTIFY_USERNAME` | (unset) | api | User for HTTP Basic login to the notification server, together with `UT_NOTIFY_PASSWORD` (no `:`); needs `UT_NOTIFY_HOST`. Prefer the Docker secret. |
| `UT_NOTIFY_PASSWORD` | (unset) | api | Password for that HTTP Basic login. Prefer the Docker secret. |
| `UT_NOTIFY_HOST` | (unset) | api | Host name (optional `:port`, default 443) the notification credentials may go to, for example `ntfy.example.com`. Required with credentials; a target URL on any other host gets none (deploy/README.md, "Notifications with ntfy"). |
| `UT_WEB_ENABLED` | `true` | api | Serve the web player at `/web`; off, every `/web` path answers 404. |
| `UT_WEB_SESSION_TTL_S` | `604800` | api | Lifetime of a web player session (7 days; between 5 minutes and 30 days). Its cookies are signed with `UT_ADMIN_SESSION_SECRET`. |
| `UT_BOOTSTRAP_ADMIN_USERNAME` | (unset) | api | With `UT_BOOTSTRAP_ADMIN_PASSWORD`: creates the first admin when the api starts with no users. There is never a default password. |
| `UT_BOOTSTRAP_ADMIN_PASSWORD` | (unset) | api | Password of that first admin (12 characters or more). Remove it once the admin exists (deploy/README.md, "Bootstrap admin password"); `docker compose exec api ultimatetunes bootstrap-admin <name>` asks for it instead. |
| `UT_AUTH_MAX_FAILURES_PER_IP` | `10` | api | Failed sign-ins or key checks from one IP (IPv6: its /64) before that IP is locked for `UT_AUTH_LOCKOUT_S`. |
| `UT_AUTH_MAX_FAILURES_PER_USER` | `5` | api | Failed password checks of one username **from the admin networks** (LAN/Tailscale) before it is locked there for `UT_AUTH_LOCKOUT_S`. From outside, a username is never locked: it gets a growing delay (below); this count only decides when the streak is logged and audited. |
| `UT_AUTH_LOCKOUT_S` | `900` | api | How long a locked IP, or a username locked from the admin networks, stays locked. |
| `UT_AUTH_OUTSIDE_BACKOFF_BASE_S` | `1` | api | Delay after one failed password check of a username from outside the admin networks (web sign-in, `POST /ut/v1/keys`); it doubles with each consecutive failure and a success resets it. |
| `UT_AUTH_OUTSIDE_BACKOFF_MAX_S` | `300` | api | Longest such delay. A stranger sending one wrong password per window can keep a user's outside sign-in waiting; sessions, API keys and LAN/Tailscale sign-ins are not affected (SECURITY.md). |
| `UT_AUTH_KEY_RATE_PER_S` | `50` | api | Requests per second each API key may make (token bucket refill). |
| `UT_AUTH_KEY_BURST` | `200` | api | Burst of requests each API key may make at once. |
| `UT_AUTH_LOGIN_RATE_PER_S` | `0.2` | api | Password checks per second per IP (refill). |
| `UT_AUTH_LOGIN_BURST` | `5` | api | Burst of password checks per IP. |
| `UT_AUTH_ARGON2_CONCURRENCY` | `2` | api | Password hashes computed at once (each takes memory and CPU). |
| `UT_AUTH_ARGON2_WAIT_S` | `2` | api | How long a password check waits for a free slot before answering "try again". |
| `UT_AUTH_MAX_FAILURES_GLOBAL_PER_MIN` | `100` | api | Failures per minute from outside the admin networks before unknown keys, and the outside password checks of usernames that failed recently, are locked. Usernames with no recent outside failure, valid keys and the admin networks are never held back by it. |
| `UT_AUTH_GLOBAL_LOCKOUT_S` | `60` | api | Length of that global lock. |

## Downloads and their limits

| Setting | Default | Container | Meaning |
|---|---|---|---|
| `UT_MAX_TRACK_DURATION_S` | `1800` | api, worker | Songs longer than this (30 minutes) are never queued, and yt-dlp refuses them again (also live streams). |
| `UT_MAX_DOWNLOAD_BYTES` | `209715200` | api, worker | Largest single download (200 MiB); the worker stops one that grows past it. |
| `UT_MAX_QUEUED_JOBS_PER_USER` | `200` | api, worker | Downloads one user may have queued or running at once; past it new requests get 429. Shown per user in the panel. |
| `UT_MAX_DOWNLOAD_BYTES_PER_DAY_PER_USER` | `5368709120` | api, worker | Bytes one user's downloads may use over the last 24 hours, rolling (5 GiB). Past it the user's new downloads are refused and their queued ones wait. Shown per user in the panel. |
| `UT_MIN_FREE_BYTES` | `2147483648` | api, worker | Below this much free space (2 GiB) on `/music` or `/staging` nothing new is queued and no job is claimed; downloads resume above 110 % of it. Shown in the panel's overview. |
| `UT_CLAIM_RETRY_AFTER_S` | `2` | api | `Retry-After` the api gives an idle worker when no job is waiting. |
| `UT_CLAIM_MAX_WAIT_S` | `25` | api | Longest the api holds a worker's long-poll claim open while nothing is claimable; 0 turns long-polling off. |
| `UT_CLAIM_POLL_S` | `1` | api | While a claim waits, how often the queue is checked again (jobs queued by another replica, retry backoffs ending). |
| `UT_MAX_LISTENERS_PER_JOB` | `8` | api | Clients that may stream one song while it downloads; past it HTTP 503 with `Retry-After`. |
| `UT_MAX_LISTENERS_PER_KEY` | `4` | api | Such streams one API key may hold at once. |
| `UT_LISTENER_RETRY_AFTER_S` | `5` | api | `Retry-After` of those 503 answers. |
| `UT_STREAM_POLL_INTERVAL_S` | `0.25` | api | How often a download with listeners is re-read when no progress report reached this api process. |
| `UT_STAGING_SWEEP_INTERVAL_S` | `300` | api | How often staging directories nobody needs are deleted; 0 turns the periodic sweep off. |

## YouTube Music, search and imports

| Setting | Default | Container | Meaning |
|---|---|---|---|
| `UT_EXTERNAL_SEARCH` | `true` | api | Off: search answers from the library only and nothing new is fetched from YouTube Music. |
| `UT_SEARCH_EXTERNAL_TIMEOUT_S` | `1.5` | api | How long a search waits for YouTube Music before answering with the library only. |
| `UT_YTM_LOCATION` | (empty) | api | Optional two-letter country for YouTube Music results (for example `ES`); empty uses the server's IP. |
| `UT_YTM_THREADS` | `3` | api | Threads talking to YouTube Music (each keeps its own session). |
| `UT_YTM_TIMEOUT_S` | `5` | api | Timeout of one request to music.youtube.com. |
| `UT_YTM_RATE_PER_S` | `2` | api | Shared budget of requests per second to music.youtube.com, for every user together (a search costs three). Shown in the panel's overview. |
| `UT_YTM_BURST` | `6` | api | Burst of that shared budget. |
| `UT_YTM_MAX_WAIT_S` | `3` | api | How long a lookup waits for the shared budget before failing as unavailable. |
| `UT_YTM_BREAKER_BASE_S` | `300` | api | After a 429/403 from YouTube Music, external calls pause this long, doubling while throttling repeats. |
| `UT_YTM_BREAKER_MAX_S` | `3600` | api | Longest such pause. |
| `UT_SEARCH_USER_RATE_PER_S` | `0.2` | api | Each user's budget of external searches (refill per second); past it search shows the library only. Shown per user in the panel. |
| `UT_SEARCH_USER_BURST` | `20` | api | Burst of each user's external searches. |
| `UT_CATALOG_USER_RATE_PER_S` | `0.5` | api | Each user's budget of uncached catalog lookups (album, artist, track, radio, playlist, covers); past it 429 until it refills. Shown per user in the panel. |
| `UT_CATALOG_USER_BURST` | `60` | api | Burst of each user's catalog lookups. |
| `UT_RADIO` | `true` | api | Off: radio and similar songs answer "feature disabled". |
| `UT_RECOMMENDATIONS` | `true` | api | Off (or `UT_RADIO` off): `/ut/v1/recommendations` answers "feature disabled". Recommendations seed the YouTube Music radio from your own plays and favourites. |
| `UT_RECOMMENDATION_SEEDS` | `4` | api | How many of your most-played and favourite songs seed the recommendations (one radio each). |
| `UT_CHARTS` | `true` | api | Off (or `UT_RADIO` off): `/ut/v1/charts` and `/ut/v1/moods` answer "feature disabled". YouTube Music's own public country charts and mood/genre playlists (no new outbound host). |
| `UT_CHARTS_COUNTRY` | `ZZ` | api | Default country for `/ut/v1/charts` (ISO 3166-1 alpha-2; `ZZ` = global). The client may override it per request. |
| `UT_LISTENBRAINZ_RECOMMENDATIONS` | `false` | api | Off by default. On: `/ut/v1/recommendations` adds a ListenBrainz shelf (an artist's community-popular recordings, matched on YouTube Music) by contacting `api.listenbrainz.org`. CC0 data, read-only public lookups; only a public artist id is sent, never your listening history. |
| `UT_LISTENBRAINZ_SEEDS` | `1` | api | How many of your favourite/most-played artists (those with a MusicBrainz id) seed the ListenBrainz lookups. |
| `UT_LISTENBRAINZ_TRACKS` | `6` | api | How many popular recordings to take from each ListenBrainz artist lookup. |
| `UT_LISTENBRAINZ_TIMEOUT_S` | `5` | api | Per request to `api.listenbrainz.org`. |
| `UT_IMPORT_CATALOG_RATE_PER_S` | `0.5` | api | Catalog lookups per second of all playlist imports together, a share of the YouTube Music budget (at most 2). |
| `UT_IMPORT_CATALOG_BURST` | `1` | api | Burst of that import budget. |
| `UT_IMPORT_MAX_ACTIVE_PER_USER` | `3` | api | Imports one user may have running at once. |

## Library, covers and lyrics

| Setting | Default | Container | Meaning |
|---|---|---|---|
| `UT_LIBRARY_SCAN_ON_START` | `true` | api | Scan `/music` in the background when the api starts (adds and updates tracks of new or changed files, never deletes). |
| `UT_COVER_CACHE_TTL_S` | `2592000` | api | How long external cover art stays in the disk cache under `/data` (30 days). |
| `UT_COVER_CACHE_MAX_BYTES` | `536870912` | api | Size cap of that cover cache (512 MiB); the oldest go first. |
| `UT_COVER_FETCH_TIMEOUT_S` | `10` | api | Timeout of one cover fetch from the YouTube image hosts. |
| `UT_LYRICS_TIMEOUT_S` | `5` | api | Timeout of one LRCLIB request. |
| `UT_LYRICS_RATE_PER_S` | `1` | api | Requests per second to LRCLIB from the whole server. |
| `UT_LYRICS_BURST` | `2` | api | Burst of LRCLIB requests. |
| `UT_LYRICS_NOT_FOUND_RETRY_DAYS` | `7` | api | A song LRCLIB had no lyrics for is asked again after this many days. |
| `UT_LYRICS_FAILURE_BACKOFF_S` | `300` | api | After a failed LRCLIB lookup, the same song is not asked again for this long. |

## Tagging (worker)

| Setting | Default | Container | Meaning |
|---|---|---|---|
| `UT_FFMPEG_PATH` | `/usr/bin/ffmpeg` | worker | ffmpeg binary in the image (remux, ReplayGain). |
| `UT_FFPROBE_PATH` | `/usr/bin/ffprobe` | worker | ffprobe binary in the image. |
| `UT_FFMPEG_TIMEOUT_S` | `300` | worker | Bound of one ffmpeg or ffprobe run. |
| `UT_MUSICBRAINZ_ENABLED` | `true` | worker | Look songs up in MusicBrainz and Cover Art Archive. Off: YouTube Music data only, and every new track is marked "needs review". |
| `UT_MUSICBRAINZ_MIN_SCORE` | `0.85` | worker | A MusicBrainz match scoring below this (0 to 1) keeps the YouTube Music data and marks the track "needs review" in the panel's Library page. |
| `UT_METADATA_TIMEOUT_S` | `15` | worker | Timeout of one request to MusicBrainz, Cover Art Archive or the YouTube thumbnail host. |
| `UT_COVERS_ENABLED` | `true` | worker | Fetch cover art (Cover Art Archive first, then the YouTube thumbnail). |

## Worker and yt-dlp

| Setting | Default | Container | Meaning |
|---|---|---|---|
| `UT_API_URL` | `http://api:8045` | worker | The api's internal worker API, over the internal Docker network. |
| `UT_WORKER_ID` | (unset) | worker | Stable name of this worker in the panel; unset uses the hostname and process id. |
| `UT_LEASE_S` | `60` | worker | Lease asked for each claimed job; heartbeats come every third of it. A crashed worker's job goes to another one after the lease ends. |
| `UT_POLL_INTERVAL_S` | `2` | worker | Wait before claiming again when the api is unreachable or did not say. |
| `UT_CLAIM_WAIT_S` | `8` | worker | Long poll: how long an idle claim asks the api to wait for a job; 0 polls instead. |
| `UT_API_TIMEOUT_S` | `10` | worker | Timeout of one call to the api. |
| `UT_API_RETRIES` | `3` | worker | Retries of an idempotent call to the api after a transport error or a 5xx. |
| `UT_STATUS_INTERVAL_S` | `300` | worker | How often the worker reports its versions and picks up admin commands ("update yt-dlp now", "run the canary now"). |
| `UT_BLOCKED_PAUSE_S` | `1800` | worker | When YouTube blocks downloads (429, bot check), the worker stops claiming this long, doubling while blocks continue. |
| `UT_BLOCKED_PAUSE_MAX_S` | `14400` | worker | Longest such pause. |
| `UT_FAKE_DOWNLOAD_CHUNKS` | `8` | worker | Test stack only: chunks the fake downloader writes. |
| `UT_FAKE_DOWNLOAD_DELAY_S` | `0.05` | worker | Test stack only: pause between those chunks. |
| `UT_YTDLP_DIR` | `/opt/ytdlp` | worker | The worker's own volume with the live, self-updated yt-dlp. |
| `UT_YTDLP_SEED_DIR` | `/opt/ytdlp-seed` | worker | The verified yt-dlp copy shipped in the image, used to seed an empty volume. |
| `UT_YTDLP_KEYRING` | `/usr/local/share/ultimatetunes/yt-dlp-keyring.gpg` | worker | Keyring with the yt-dlp release signing key; updates are installed only when their signature verifies. |
| `UT_YTDLP_KEY_FINGERPRINT` | `AC0CBBE6848D6A873464AF4E57CF65933B5A7581` | worker | Fingerprint of that signing key (40 hex digits). |
| `UT_YTDLP_CHANNEL` | `stable` | worker | `stable` or `nightly` yt-dlp releases. |
| `UT_YTDLP_AUTO_UPDATE` | `true` | worker | Check GitHub for a newer signed yt-dlp every `UT_YTDLP_UPDATE_INTERVAL_H`. The panel's "Update yt-dlp now" works either way. |
| `UT_YTDLP_UPDATE_INTERVAL_H` | `24` | worker | Hours between update checks. |
| `UT_YTDLP_UPDATE_TIMEOUT_S` | `300` | worker | Bound of one whole update (download, signature check, smoke test). |
| `UT_YTDLP_UPDATE_ON_ERROR_MIN_INTERVAL_S` | `3600` | worker | An extractor error triggers an update check at most this often. |
| `UT_YTDLP_PLAYER_CLIENTS` | `default` | worker | yt-dlp player clients, comma separated (`--extractor-args youtube:player_client=...`). |
| `UT_YTDLP_FALLBACK_CLIENTS` | `web_embedded` | worker | Clients tried once more when the first ones fail; empty turns the fallback off. |
| `UT_YTDLP_TIMEOUT_S` | `600` | worker | Bound of one yt-dlp download. |
| `UT_DENO_PATH` | `/usr/local/bin/deno` | worker | The JavaScript runtime yt-dlp needs. |
| `UT_GPGV_PATH` | `/usr/bin/gpgv` | worker | gpgv binary that verifies yt-dlp updates. |
| `UT_YTDLP_POT_PROVIDER_URL` | (unset) | worker | Optional PO token provider (decision D13): base URL of the bgutil HTTP server, `http://bgutil:4416` with compose's `pot` profile (the provider's alias on the `pot` network). Unset or empty: yt-dlp loads no plugin, exactly as before. Only `http(s)://host[:port]` is accepted, with a Docker service name (one label starting with a letter) or an address in `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `127.0.0.0/8`, `::1` or `fc00::/7` (no IPv6 zone id, no IPv4-mapped or 6to4 form, no port 0); anything else stops the worker at start. See [admin-guide.md](admin-guide.md), "Sign in to confirm you're not a bot". |
| `UT_YTDLP_PLUGIN_DIR` | `/opt/ytdlp-plugins` | worker | Read-only folder in the image with the pinned bgutil yt-dlp plugin, pruned to its HTTP provider (`bgutil-http.zip`); the only plugin folder yt-dlp searches, and only when `UT_YTDLP_POT_PROVIDER_URL` is set. |
| `UT_YTDLP_COOKIES_FILE` | (unset) | worker | Optional fallback path of a Netscape/Mozilla `cookies.txt` exported from a **throwaway** YouTube account, normally the read-only Docker secret `ut_ytdlp_cookies` at `/run/secrets/ut_ytdlp_cookies`; the path must sit inside `/run/secrets`. Unset or empty: no cookies (as before). yt-dlp rewrites the cookies file in place, so the worker copies it to a private 0600 temp per download and deletes it afterwards, and passes `--cookies <copy>`. The content is an account credential, never logged. See [admin-guide.md](admin-guide.md), "Signing in with a YouTube account". |

## Canary

| Setting | Default | Container | Meaning |
|---|---|---|---|
| `UT_CANARY_ENABLED` | `true` | api, worker | Run the canary on a schedule: catalog checks in the api, one test download in the worker. The panel's "Run the canary now" works either way. |
| `UT_CANARY_INTERVAL_H` | `24` | api, worker | Hours between scheduled runs. |
| `UT_CANARY_FIRST_DELAY_S` | `120` | api, worker | Wait after start before the first scheduled run. |
| `UT_CANARY_POLL_S` | `60` | api | How often the api looks for a due run or an admin request. |
| `UT_CANARY_TIMEOUT_S` | `300` | api, worker | Bound of one check (a catalog call, or the whole test download). |
| `UT_CANARY_VIDEO_ID` | `6pEWHaIhxOg` | api, worker | The fixed Creative Commons track the canary downloads and looks up (docs/compat.md). |
| `UT_CANARY_QUERY` | `Kevin MacLeod Sauropod Spotting` | api | What the canary's search check asks for. |
| `UT_CANARY_PLAYLIST_ID` | `PLx53r85FKaLyGUec4f9LJUXuCfrFRUV15` | api | The playlist the canary's playlist check reads. |
| `UT_CANARY_STATE_FILE` | `/opt/ytdlp/canary-state.json` | worker | Where the worker remembers its last canary run (it has no database). |

## Compose variables

These are not read by the server: Docker Compose substitutes them into the compose files. Put them in the `.env` file next to the compose file.

| Variable | Used in | Meaning |
|---|---|---|
| `UT_VERSION` | `server/compose.yaml` | Image tag to run (required; `local` for an image you built). |
| `UT_MUSIC_PATH` | `server/compose.yaml` | Your music folder on the host, mounted at `/music` (required). |
| `UT_BIND` | `server/compose.yaml` | Host address and port the client listener is published on (default `127.0.0.1:8044`: local only; reach it through `tailscale serve` or a reverse proxy). |
| `UT_TEST_IMAGE_TAG` | `server/compose.test.yaml` | Tag of the test image built from source (default `test`; `tools/ci-local.sh` uses `ci-local` so a running test stack keeps its image). |
| `UT_INTERNAL_SUBNET` | `server/compose.yaml`, deploy examples | Subnet of the api-worker `internal` network (default `10.213.44.0/24`); change it if it overlaps yours. |
| `UT_API_INTERNAL_ADDRESS` | `server/compose.yaml` | The api's fixed address on that network (default `10.213.44.250`). |
| `UT_EGRESS_SUBNET` | `server/compose.yaml`, deploy examples | Subnet of the worker's `egress` network to the Internet (default `10.213.45.0/24`). |
| `COMPOSE_PROFILES` | `server/compose.yaml` | Docker Compose's own variable: `pot` starts the optional PO token provider (`pot-provider`); also set `UT_YTDLP_POT_PROVIDER_URL`. Unset: no provider runs. |
| `UT_POT_SUBNET` | `server/compose.yaml` | Subnet of the `pot` network that only the worker and `pot-provider` share (default `10.213.47.0/24`). |
| `UT_POT_PROVIDER_ADDRESS` | `server/compose.yaml` | The provider's fixed address on it (default `10.213.47.250`), the only address it listens on. |
| `UT_PROXY_SUBNET` | `deploy/traefik/` | Subnet of the network shared with Traefik (default `10.213.46.0/24`). |
| `UT_TRAEFIK_ADDRESS` | `deploy/traefik/` | Traefik's fixed address on it (default `10.213.46.2`), the only trusted proxy. |
| `UT_PUBLIC_HOST` | `deploy/traefik-cloudflared/` | Public host name of the server (for example `music.example.com`). |
| `UT_TRAEFIK_NETWORK` | `deploy/traefik-cloudflared/` | Name of the existing Traefik Docker network (default `traefik`). |
| `UT_TRAEFIK_SUBNET` | `deploy/traefik-cloudflared/` | Subnet of that network (required). |
| `UT_TRAEFIK_ENTRYPOINT` | `deploy/traefik-cloudflared/` | Traefik entry point for HTTPS (default `websecure`). |
| `UT_TRAEFIK_CERTRESOLVER` | `deploy/traefik-cloudflared/` | Traefik certificate resolver (default `letsencrypt`). |
| `UT_AUTHELIA_MIDDLEWARE` | `deploy/traefik-cloudflared/` | Traefik middleware that puts Authelia in front of `/admin` (default `authelia@file`). |
| `UT_EDGE_LAN_RANGES` | `deploy/traefik-cloudflared/` | LAN ranges Traefik lets reach `/admin` directly; requests through the Cloudflare tunnel never pass (required). |

The deploy examples also pass several server settings through (`UT_TRUSTED_PROXIES`, `UT_ADMIN_ALLOWED_NETWORKS`, the download limits, `UT_LOG_LEVEL`, ...): their meaning is in the tables above.
