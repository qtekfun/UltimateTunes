<!--
SPDX-FileCopyrightText: 2026 UltimateTunes contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Admin guide

How to run an UltimateTunes server day to day from its admin panel. Installing it is in the [README](../README.md#self-host-it-on-your-homelab) and [deploy/README.md](../deploy/README.md); every setting is in [configuration.md](configuration.md); how the containers talk to each other is in [architecture.md](architecture.md).

## Reaching the panel

The panel lives at `/admin` on the api's client port, for example `https://music.example.com/admin`.

- It needs **HTTPS** (for example `tailscale serve`, or a reverse proxy such as Caddy) or `localhost`: the session cookie is `Secure`.
- Only the networks in `UT_ADMIN_ALLOWED_NETWORKS` reach it (loopback, private LAN ranges and Tailscale by default). Anything else gets 403, even with the right password. Behind a reverse proxy, set `UT_TRUSTED_PROXIES` to the proxy's single address, or the panel refuses proxied requests ([deploy/README.md](../deploy/README.md#reverse-proxies-and-the-client-address-ut_trusted_proxies)).
- Only accounts with the **Administrator** role can sign in. The first admin is created once from the command line: `docker compose run --rm api bootstrap-admin <name>` (it asks for the password).
- A session lasts 8 hours (`UT_ADMIN_SESSION_TTL_S`). **Sign out** ends every session of your account, on every browser. Set `UT_ADMIN_SESSION_SECRET` (a Docker secret) or sessions also end whenever the api restarts.
- The panel is in English, or in Spanish when the browser prefers Spanish. It follows the system's light or dark mode, and works on a phone (tables turn into one card per row).
- Every change in the panel carries the session's form token (CSRF protection) and is written to the audit log. Actions that cannot be undone ask for confirmation first.

The pages, in the order of the menu:

| Page | What it is for |
|---|---|
| Overview | What needs attention now, counters, disk space, YouTube Music state, version. |
| Users | Accounts, roles, passwords, and each user's share of the limits. |
| API keys | One key per device: create (with a QR code), see last use, revoke. |
| Downloads | The download queue: filter by state, retry, cancel. |
| Library | Disk usage, songs that need review, deleting tracks and albums. |
| yt-dlp | Workers and their yt-dlp version, canary runs, "update now" and "run the canary now". |
| Audit log | Who did what, when and from where, with filters. |
| Notifications | Where failed downloads, failed canary runs and low disk space are reported (ntfy or a webhook). |

## Overview

The **Needs attention** box lists only what is wrong right now, each item with a link to the page that fixes it:

- **Downloads are paused: low disk space**: `/music` or `/staging` has less than `UT_MIN_FREE_BYTES` (2 GiB) free. Nothing new is queued and workers claim nothing until free space is back above 110 % of the minimum. Free some space (delete albums from the Library page, or grow the volume); downloads resume by themselves.
- **A volume is below the free-space minimum**: the same check, seen before the first refused download.
- **YouTube Music is throttling this server**: YouTube Music answered 429 or 403, so external calls pause for 5 minutes, doubling up to an hour while it continues. Searches show the library only meanwhile. Nothing to do but wait; if it keeps happening, lower the traffic (fewer users, `UT_YTM_RATE_PER_S`).
- **The shared YouTube Music request budget is used up**: lookups are waiting for `UT_YTM_RATE_PER_S` to refill. A moment of this is normal during a big import; if it stays, someone is using more than their share (see Users).
- **The last canary run failed**: see [yt-dlp and the canary](#yt-dlp-and-the-canary).
- **No worker has reported yet**: no worker has contacted the api. Check that the `worker` container runs and shares `UT_WORKER_TOKEN` with the api (`docker compose logs worker`).
- **N failed downloads**, **N tracks need review**: links to the Downloads and Library pages.

When nothing is wrong it says **Everything looks fine.** Below it: counters (each one links to its page), the bytes downloaded by everyone in the last 24 hours, free space of both volumes, the shared YouTube Music budget, the last canary run, and the workers. The server version is at the bottom of every page.

## Users

The table shows, for every account:

- **Role** (Administrator or User) and **Status** (Active or Disabled), and the last sign-in to the panel.
- **Downloads**: jobs the user has queued or running, against `UT_MAX_QUEUED_JOBS_PER_USER` (200).
- **Downloaded in 24 h**: bytes the user's downloads used over the last 24 hours, against `UT_MAX_DOWNLOAD_BYTES_PER_DAY_PER_USER` (5 GiB). The bar turns amber at 80 % and red at 100 %. At 100 % the user's new downloads are refused and their queued ones wait (another user asking for the same song takes it over).
- **Catalog / search left**: what is left of the user's YouTube Music budgets: uncached catalog lookups (`UT_CATALOG_USER_BURST`, 60) and external searches (`UT_SEARCH_USER_BURST`, 20). They refill over time; amber means 20 % or less is left. An empty catalog budget answers 429; an empty search budget makes search show the library only.

### Create a user

1. Fill in **New user**: a username (stored in lower case), a password of 12 characters or more, and the role. Give **Administrator** only to people who run the server.
2. Tell the person their username and password through a private channel. They do not need it on their phone: devices use API keys.
3. Create an API key for each of their devices (next section).

### Change a password, a role, or disable someone

- **Set password**: type the new password in the row and press **Set password**. Their API keys keep working.
- **Make administrator** / **Make user**: changes the role (asks for confirmation). You cannot change your own role.
- **Disable**: the account can no longer sign in and **all its API keys stop working** at once, without being revoked (asks for confirmation). **Enable** brings them back. You cannot disable yourself. Use this for someone who should lose access for a while; revoke keys when a device is lost.

## API keys

Every device (phone, tablet, another OpenSubsonic app) gets its own key, so one can be revoked without touching the others. A key is 256 random bits, shown **once** and stored only as a hash.

### Give a device a key

1. Choose the **User**, a **Device name** you will recognise later (for example "Pixel phone"), and the **Server address the app will use**: the https address the device reaches, such as your `tailscale serve` name. It is prefilled from `UT_ADMIN_PUBLIC_URL` when set.
2. Press **Create key**. The page shows the server address, the key and a QR code with both (`ultimatetunes://connect?url=...&key=...`).
3. On the Android phone, open the camera app and point it at the QR code. The camera recognises it and offers to open UltimateTunes (on some phones through Google Lens or a "scan QR code" tile). The app shows the server address and asks before connecting; it connects only after the server and the key both check out, and if it was already connected it keeps the old server until then. You can also open the app's **Connect** screen and type the server address and the key. Other OpenSubsonic apps take it as their API key (`apiKey` authentication; the older `t`/`s` token authentication is refused).
4. Leave the page: the key is never shown again. If you lose it before typing it in, revoke it and create another.

The list shows each key's prefix (the first characters, to tell keys apart), when it was created, its last use (time and address), and whether it is active.

### Revoke a key

Press **Revoke** in its row and confirm. That device is signed out at once and cannot use the key again; the user's other devices are not affected. Do this when a device is lost, sold or no longer used. Revoked keys stay in the list (at the bottom) for the record.

## Downloads

The queue, newest first, 50 per page, refreshing itself every 5 seconds. Filter by state with the links on top: **queued**, **downloading**, **tagging**, **ready**, **failed**, **cancelled** (with counts). Each row shows the song, its YouTube video id, progress, attempts, who asked for it, the last update and the error, if any.

- A download that fails for a passing reason is tried again by itself (after 30 s, 2 min and 8 min) up to 3 attempts, then ends as **failed**. A permanent error (for example a removed video) fails at once.
- **Retry** (failed or cancelled downloads) queues it again with fresh attempts.
- **Cancel** (queued or running downloads) asks the worker to stop; a running one shows "cancel requested" until the worker notices. Anyone streaming it is cut off.

### Watch the downloads

Keep the page open: it refreshes on its own. Common errors:

| Error | Meaning and what to do |
|---|---|
| `video_unavailable` | Removed, private, region-blocked or age-gated video. Retrying will not help. |
| `format_unavailable` | No Opus or M4A audio offered for it. Retrying will not help. |
| `extractor_error` | The downloader could not read the page, usually a YouTube change: update yt-dlp (below), then **Retry**. |
| `rate_limited_upstream` | YouTube throttled or blocked the worker; it pauses claiming by itself (`UT_BLOCKED_PAUSE_S`). Wait, then retry. |
| `network_error` | Timeout or connection error; tried again by itself. |
| `tagging_failed`, `storage_error` | The file could not be processed or moved into `/music`. Check `docker compose logs worker` and free space. |
| `lease_expired` | The worker stopped mid-download (restart, crash); tried again by itself. |

The full list is in [contracts/errors.md](../contracts/errors.md#worker-error-codes-fail--job-errorcode). Songs over `UT_MAX_TRACK_DURATION_S` or `UT_MAX_DOWNLOAD_BYTES` are refused before or while downloading.

Many failures at once usually mean yt-dlp needs an update: see the next section but one.

## Library

Counters of tracks, albums, artists and the size of the music files, and the used and free space of `/music` (a "?" means the volume could not be read: check the mount).

### Fix "needs review"

When a song is downloaded the worker looks it up in MusicBrainz. If no match scores at least `UT_MUSICBRAINZ_MIN_SCORE` (0.85), the song keeps the YouTube Music title, artist, album and cover, and is listed under **Need review**, 50 per page. For each one:

1. Play it in the app (or check its tags) and decide.
2. Tags look right: press **Mark reviewed**. It leaves the list and nothing else changes.
3. Tags are wrong or it is the wrong song: tick **Sure** and press **Delete** (asks for confirmation). The track and its file are removed; searching for it again downloads it anew.

Correcting tags is not possible from the panel; edit the file with your usual tag editor, then rescan: the api scans `/music` when it starts, or run `docker compose run --rm api scan-library`.

### Delete tracks or albums

Search by title or album name under **Find tracks and albums to delete** (the first 200 matches are shown), tick **Sure** and press **Delete**, then confirm. The rows go first, then the files, best effort: if a file cannot be removed the page says so and the logs say which. A track that is downloading cannot be deleted; cancel it first. Playlists that contained it are renumbered.

## yt-dlp and the canary

YouTube changes often and yt-dlp follows. The worker keeps yt-dlp current by itself: every `UT_YTDLP_UPDATE_INTERVAL_H` (24 h), and after an extractor error, it downloads the newest release from GitHub and installs it only if its signature verifies against the pinned yt-dlp key.

The **canary** is a daily test with one fixed Creative Commons song (`UT_CANARY_VIDEO_ID`): the api runs a search, a radio, an album and a playlist lookup, and the worker downloads the song to staging and deletes it. A failed canary is the earliest sign that YouTube changed something.

The page shows:

- **Workers**: each worker's id, server version, yt-dlp version and last report. A worker that stops reporting is not running.
- **Canary runs**: the last ten, with source (api or worker), result, yt-dlp version and message.
- **Commands**: the last commands sent to the workers and when a worker picked them up.

### Update yt-dlp now

Press **Update yt-dlp now** after a wave of failed downloads. The command waits until the next worker report (every `UT_STATUS_INTERVAL_S`, 5 minutes by default) and shows as "waiting" until then. Pressing it again while one waits does nothing. The new version appears in the Workers table after the following report.

### Run the canary now

Press **Run the canary now** to check right away, for example after an update. Results appear under Canary runs within minutes. If it keeps failing with the newest yt-dlp, look at the yt-dlp issue tracker; there is nothing to fix on the server side.

## Audit log

Every sign-in to the panel, every account and key change, and every action taken in the panel (retries, cancels, deletes, reviews, worker commands, notification settings), newest first, 50 per page. Each entry has the time (UTC), who did it, from which address, the action, its target and a short detail. Passwords, keys and notification URLs are never recorded.

Filter by **Action** (for example `key.revoke` or `user.disable`) and by **Who**, then **Filter**; **Clear** removes the filters. Typical questions:

- Who revoked this key? Filter by `key.revoke`.
- Did anyone sign in to the panel from an unknown address? Filter by `admin.login` and read the **From** column.
- What did a given admin change? Filter by **Who**.

## Notifications

Optionally, the server reports failed downloads, failed canary runs and low disk space to an [ntfy](https://ntfy.sh) topic or a webhook. Choose the kind, enter the https URL, **Save**, then **Send a test notification**. The server contacts only that address, and refuses loopback, link-local and similar local addresses. The checks run every `UT_ADMIN_NOTIFY_INTERVAL_S` (60 s). For an ntfy server that requires a login, set `UT_NOTIFY_TOKEN` (or `UT_NOTIFY_USERNAME` and `UT_NOTIFY_PASSWORD`) and `UT_NOTIFY_HOST` as Docker secrets or environment variables and restart the api; the page then shows which kind is set and warns when the URL is not on that host, because credentials are sent only there. They are never typed into the panel ([deploy/README.md, "Notifications with ntfy"](../deploy/README.md#notifications-with-ntfy)).

## Backups and restore

`/data` (the database: users, keys, playlists, play counts) and `/music` (the files) are all there is to back up. The online copy of the database and a restore test are in [deploy/README.md, "Backups of /data"](../deploy/README.md#backups-of-data-and-a-restore-test). Test a restore before you need one.

## Where else to look

- `docker compose logs api` and `docker compose logs worker`: JSON logs, secrets redacted.
- `/readyz` from an admin network: whether the database, schema, storage and downloads are OK.
- [SECURITY.md](../SECURITY.md) for the threat model and how to report a vulnerability.
