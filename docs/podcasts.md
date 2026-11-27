<!--
SPDX-FileCopyrightText: 2026 UltimateTunes contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Podcasts: design

Podcasts as in Spotify: find a show, follow it, get its new episodes, resume where you left off, on every device, also offline. Decided by the owner on 2026-11-27 (SPEC §11); tasks in PLAN Wave 5.

## Decisions
- **Sources, in two phases.** Phase 1: YouTube Music (`ytmusicapi` search and podcast pages, `yt-dlp` for the audio): no new host. Phase 2: any podcast by its **RSS** address, and OPML import and export. No podcast directory in either phase.
- **Episodes are kept and expire.** The server downloads an episode when someone plays it or asks for it, or when it is new in a followed show with automatic download. It frees it later (rules below).
- **Features:** follow, new episodes, resume, played marks, playback speed, skip back 15 s and forward 30 s, sleep timer, description with chapters, automatic download, notice of new episodes.

## Model
- A **show** has a source (`youtube` or `rss`), a title, author, description and cover. An **episode** has a title, date, duration, description and a state on the server: `remote` (known, no file), `downloading`, `ready`, `failed`.
- Per user: the shows followed (with playback speed and automatic download), and per episode the position, played or not, "keep", and when that last changed.
- Episodes are **not songs**: they never appear in song listings, search results for music, radio, the library size limit or the "whole library offline" sync. Their files live apart from the music under the `LibraryStore`.
- No music tagging (MusicBrainz) and no ReplayGain for episodes.

## Server
- **API.** The OpenSubsonic podcast endpoints (`getPodcasts`, `getNewestPodcasts`, `getPodcastEpisode`, `createPodcastChannel`, `deletePodcastChannel`, `downloadPodcastEpisode`, `deletePodcastEpisode`, `refreshPodcasts`) so third-party clients work, and `/ut/v1/podcasts/…` for what they lack: search, progress, per-show settings, chapters.
- **Refresh.** Followed shows are checked on a schedule (every few hours, spread out, with backoff), within the same request budget as the music catalog.
- **Downloads.** The existing job queue, below music in priority; limits on length and size per episode.
- **Expiry.** An episode is freed when every follower has played it and some days have passed, or when it is older than a maximum age, unless someone keeps it. A total size limit for podcasts, separate from the music one; the oldest go first. A freed episode goes back to `remote` and can be downloaded again. The numbers are settings of the admin panel.
- **Progress.** The client sends position and played marks with the time they happened; the newest wins.

## Android (three-tab design)
No new tab: **Home** gets "New episodes" and "Continue listening"; **Library** gets a "Podcasts" filter; **Search** gets a "Podcasts" filter; a show page and an episode page (description, chapters).
- The player in episode mode: speed, skip 15/30 s, sleep timer (also for music), chapters, no radio or lyrics.
- The local catalog (T32) holds shows, episodes and progress; progress made offline goes through the pending changes (T35).
- Downloads and expiry on the phone: the last N unplayed episodes of a show, Wi-Fi only by default; played ones are removed.
- **New episodes** are noticed by the app itself (periodic WorkManager check against the user's server), with a local notification. There is no push service. This amends RF-13.
- Chapters come from the timestamps in the description.
- A link in a description opens the browser only when tapped.

## Phase 2: RSS, and what it changes
RSS means the server and the worker fetch **addresses that users type**, on any host. Today that is forbidden (security rules: no server-side request to arbitrary URLs; closed list of hosts). Phase 2 starts only once the owner has approved the new rule. Proposal:
- HTTPS by default; plain HTTP only with an explicit server setting.
- Resolve the name and refuse loopback, private, link-local, carrier-grade NAT (which covers Tailscale) and other non-public addresses; connect to the checked address; check again on every redirect.
- Limits on redirects, size, time and content type; a hardened XML parser (no external entities). A new dependency for it needs approval.
- Only admins, or users the admin allows, may add a feed.
- Episode covers and audio are fetched by the server; the app still talks only to its server.
- A security review of the whole phase before it is released.

## Risks to settle first (spike T40)
- `ytmusicapi` podcast calls without an account, from the server.
- `yt-dlp` on episodes: formats, size, time, and the bot wall.
- **Long episodes and streaming while downloading** (T03a): seeking on a first play is limited, and resuming at minute 40 of an episode not yet downloaded needs it. The spike decides between waiting for the download, downloading ahead, or another container.

## Not included
Podcast directories (Podcast Index, Apple), video podcasts, transcripts, comments or ratings, publishing your own podcast, podcasts in the web player (can follow later).
