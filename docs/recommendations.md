<!-- SPDX-FileCopyrightText: 2026 UltimateTunes contributors -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Music recommendations — design proposal

What the owner asked for: recommendations "based on what I listen to, from public platform
lists, national radios, etc." This document lays out the options, flags which ones would need a
**new outbound host or dependency** (forbidden until the owner approves, CLAUDE.md), and records
what is **implemented now** versus what stays a **ready-to-approve proposal**.

Hard rules this design keeps (CLAUDE.md, SPEC §6):

- The Android app talks only to the user's server. The **server** is the one that fetches any
  external info; a new outbound host is added only with the owner's approval and only after its
  data license and API terms are verified (each host is added to CLAUDE.md and `docs/architecture.md`).
- No telemetry, no analytics, no non-free data source, and the user's listening history never
  leaves the server — external lookups use only public, anonymous identifiers.

**Status (2026-10-13):** option **A** (first PR), options **B** (YouTube Music charts and moods, no
new host) and **C** (ListenBrainz, `api.listenbrainz.org`, owner-approved, **off by default**) are
implemented. Option **E** (stations) is not wired — SomaFM is rejected by its ToS, Radio Paradise is
uncertain, and a generic admin-configurable feed is the proposed path. Details per option below.

## How recommendations fit the existing architecture

The server already has every piece needed for the safe baseline:

- **The data**: per-user play history (`play_history`), play counts (`user_track_stats`) and
  favourites (`starred_tracks`) are in the database (schema `0001_init.sql`). No new table or
  migration is needed.
- **The engine**: `MusicCatalog.radio(video_id, limit)` is the YouTube Music *watch playlist*
  ("start radio from this song"), already used by `GET /ut/v1/radio` and `getSimilarSongs2`
  (PLAN T07). It reaches YouTube Music through `ytmusicapi`, an **already-approved** host.
- **The mapping**: results are mapped *local-first* exactly like radio — a video already in the
  library becomes the library song (with the caller's stars and play counts), a `pending`/
  `failed` one keeps its `yt:` id and `libraryState`. `search.render.track_item` renders them.

So "recommend from what I listen to" is: pick the caller's most-played and favourite songs as
**seeds**, start the existing radio from each, drop the seeds and the songs the caller already
plays, and keep the rest. No new host, no new dependency, no new table.

## The options

| # | Source | New host / dependency? | Free-software / ToS | Status |
|---|--------|------------------------|---------------------|--------|
| A | **Your own plays + favourites → existing YouTube Music radio** | **No** (reuses `ytmusicapi`) | Same grey area as the rest of the app (personal use, never offered to third parties); no extra data source | **Implemented** (first PR) |
| B | **YouTube Music charts & moods** (`get_charts`, `get_mood_playlists`) | **No** (reuses `ytmusicapi`) | Same as A | **Implemented** (2026-10-13): `GET /ut/v1/charts`, `/ut/v1/moods`, `/ut/v1/moods/{id}` |
| C | **ListenBrainz** popular recordings per artist | **Yes** — `api.listenbrainz.org` | Free data (CC0 / public domain via the MetaBrainz social contract), read-only, GPL-compatible | **Implemented** (2026-10-13, owner approved the host); **off by default** |
| D | **MusicBrainz / ListenBrainz "similar artists"** by MBID | **Partly** — MusicBrainz host is already approved for tagging; ListenBrainz is new | Free (CC0) | Folded into C (the public, no-auth signal on `api.listenbrainz.org` is popularity, not similar-artists; see below) |
| E | **National radio / public station playlists** (e.g. Radio Paradise, SomaFM, or a station's public "now playing" API) | **Yes** — one new host per station | Varies per station; **must** be checked individually | **Not wired** — SomaFM rejected (ToS forbids it), Radio Paradise uncertain, generic admin feed proposed; see below |

### A. From your own plays and favourites (implemented — the safe baseline)

**Data source**: the server's own `user_track_stats`, `play_history` and `starred_tracks`, plus
the already-approved YouTube Music watch playlist.

**New host/dependency**: none.

**How it works** (`server/src/ultimatetunes/radio/recommendations.py`):

1. Pick the caller's **seeds**: their most-played songs and favourites, best first (play count,
   then "starred", then recency). Each seed must resolve to a video id (its own `yt_video_id`,
   else its oldest `yt:` alias); seeds without one are skipped. Default: up to
   `UT_RECOMMENDATION_SEEDS` (4) seeds, deduplicated by video.
2. For each seed, call the existing `MusicCatalog.radio` (the YouTube Music watch playlist).
3. Drop the seed's own video, the other seeds' videos, and any song the caller **already plays**
   (so the shelves surface genuinely new music, not what they already have on repeat). Songs too
   long to ever download are dropped unless already archived (same rule as radio).
4. Map local-first and build two kinds of shelf:
   - `recommendedForYou`: the songs the most seed-radios agree on, ranked by that agreement;
   - `becauseYouPlayed`: one shelf per seed (the seed song and the new songs of its radio).

**Exposed as**: `GET /ut/v1/recommendations?limit=` (API key required). Items are `TrackItem`s,
the same shape as radio and Listen Now, so the client renders them with existing code. It is a
separate endpoint from `/ut/v1/listen-now` because Listen Now is contractually **library only**
(cheap, no YouTube Music request on every app start), whereas recommendations call YouTube Music
and are charged to the caller's rate-limit bucket like `/ut/v1/radio`.

**Cost/caching**: up to `UT_RECOMMENDATION_SEEDS` radio calls per request; each goes through the
shared `TtlCache` and per-user rate limiter, so repeat calls are cheap. Empty history ⇒ empty
response and **no** catalog call.

**Switches**: `UT_RECOMMENDATIONS` (default on) and `UT_RECOMMENDATION_SEEDS` (default 4).
Recommendations also require `UT_RADIO` on, since they reuse the watch playlist.

### B. YouTube Music charts and moods (proposed — no new host)

**Data source**: YouTube Music's own public endpoints, through the already-approved
`ytmusicapi`:

- `get_charts(country="ES"|"ZZ"|…)` — top songs/videos playlists and top artists, **per country**
  (ISO 3166-1 alpha-2; `ZZ` = global). This is the concrete answer to "charts / national lists":
  YouTube Music publishes country charts, reachable with no new host. Works unauthenticated
  (artists come back unranked, which is fine for seeding).
- `get_mood_categories()` + `get_mood_playlists(params)` — mood/genre playlists ("Chill",
  "Commute", decades, genres), the raw material for "Focus"/"Workout"-style shelves.

**New host/dependency**: none — same host as search and radio.

**Free-software/ToS**: identical to the rest of the app (personal use).

**Fit**: needs a small, additive catalog addition (`MusicCatalog.charts(country)` and
`moods()/mood_playlist(params)`), plus parsing in `search/ytmusic.py` and the fake catalog. The
country can default to a new `UT_CHARTS_COUNTRY` admin setting. Recommended as the next step
because it is the only "public lists / national" source that needs **no** new host.

**Implemented (2026-10-13)**: `MusicCatalog.charts(country)`, `moods()` and `mood_tracks(params)`
on `ytmusicapi` (with the fake, the `GuardedCatalog` cache and parsing), exposed as
`GET /ut/v1/charts?country=`, `GET /ut/v1/moods` and `GET /ut/v1/moods/{moodId}`. The chart's top
"videos" carousel is a playlist, so `charts`/`mood_tracks` fetch that playlist's songs; everything
is mapped local-first like radio. Country defaults to `UT_CHARTS_COUNTRY` (`ZZ` = global). New
`charts` capability on `/ut/v1/server`. No new host, no new dependency.

### C. ListenBrainz (implemented 2026-10-13 — new host, off by default)

**Data source**: `api.listenbrainz.org`, read-only and anonymous. The public, no-auth signal there
is **popularity**: `GET /1/popularity/top-recordings-for-artist/<artist_mbid>` returns an artist's
most-listened recordings across the MetaBrainz community (recording + artist name). For each of the
caller's favourite/most-played artists that has a MusicBrainz id (`artists.musicbrainz_id`), the
server fetches that artist's popular recordings, matches each on YouTube Music (`search_songs`), and
maps the results local-first into a "Popular on ListenBrainz · <artist>" shelf on
`/ut/v1/recommendations`.

**New host**: **yes** — `api.listenbrainz.org` (HTTPS). Approved by the owner 2026-10-13.

**License/ToS**: ListenBrainz's ToS defers to the MetaBrainz social contract — factual database
content is **public domain**, non-factual content **CC0**, and commercial use is allowed while
"charging for the content itself is forbidden". A self-hosted, non-commercial, read-only lookup is
clearly within terms. **No listening history is sent**: only a public artist MBID. (SPEC §9 lists
ListenBrainz/Last.fm *scrobbling* as out of scope; this is read-only lookup, a different use.)

**Privacy/safety**: exact constant host (no SSRF, never client input), HTTPS, `follow_redirects=False`,
`trust_env=False`, no credentials, the ListenBrainz User-Agent with a contact URL, 1 req/s
(`listenbrainz:global`, as ListenBrainz requires), 1 MiB body, `UT_LISTENBRAINZ_TIMEOUT_S` timeout.
On any failure the ListenBrainz shelf is dropped and the rest of the recommendations still return.

**Switches**: `UT_LISTENBRAINZ_RECOMMENDATIONS` (**off by default**), `UT_LISTENBRAINZ_SEEDS` (1),
`UT_LISTENBRAINZ_TRACKS` (6), `UT_LISTENBRAINZ_TIMEOUT_S` (5).

### D. MusicBrainz-based similarity (folded into C)

MusicBrainz alone has limited "similar artist" data, and ListenBrainz's richer *similar-artists*
dataset lives on its **Labs** API (`labs.api.listenbrainz.org`), a *second* host the owner did not
approve. So the ListenBrainz integration (C) uses only the main, approved host
`api.listenbrainz.org` and its public **popularity** endpoint. Similar-artists via the Labs host
stays a future proposal (needs its own host approval).

### E. National radios / public station playlists (not wired — verified per station 2026-10-13)

**SomaFM (`somafm.com`) — rejected.** Its Terms of Service (checked 2026-10-13) explicitly forbid
third-party use: *"We can't grant permission for third-party SomaFM clients or applications, even
noncommercial ones"*, and *"Scrobbling and/or automated re-posting of playlists and now playing
information is against our terms of use."* Wiring SomaFM would breach its ToS, so it is **not**
implemented and should not be.

**Radio Paradise (`api.radioparadise.com`) — uncertain, left as a proposal.** Radio Paradise
publishes a now-playing JSON feed, but it has no public API terms granting reuse of its curated
playlist/now-playing data (comparable copyright concerns to SomaFM's). Uncertain → documented, not
wired.

**Generic admin-configurable station feed — recommended design, not yet built.** Rather than
hardcoding broadcasters with uncertain ToS, the preferred path for national radio is a source where
the **admin** sets a station's host, which is added to a per-server allowlist (the admin takes ToS
responsibility for the station they choose). This keeps the SSRF rule intact (the host is still an
explicit allowlist, not free-form client input) but needs its own design for the wildly different
feed shapes (a configurable field mapping, or per-adapter parsers), so it stays a proposal here.

## What is implemented vs. proposed

- **Implemented** (first PR, no new host/dependency): option **A**, `GET /ut/v1/recommendations`.
- **Implemented** (2026-10-13, no new host): option **B** — YouTube Music charts and moods,
  `GET /ut/v1/charts`, `GET /ut/v1/moods`, `GET /ut/v1/moods/{moodId}`.
- **Implemented** (2026-10-13, owner approved the host, **off by default**): option **C** —
  ListenBrainz (`api.listenbrainz.org`), as an extra `shelves` entry on `/ut/v1/recommendations`.
- **Not wired**: option **E** — SomaFM rejected (ToS forbids it), Radio Paradise uncertain, generic
  admin-configurable feed proposed. Option **D** folded into C (similar-artists needs the Labs host,
  not approved).

### Outbound hosts

| Option | Host | Status | License / ToS basis |
|--------|------|--------|---------------------|
| A, B | `music.youtube.com` (ytmusicapi) | already approved | the app's existing source |
| C | `api.listenbrainz.org` | **approved 2026-10-13, wired, off by default** | MetaBrainz social contract: public-domain/CC0 data, commercial use allowed, read-only lookup, **no history sent** |
| E | `somafm.com` | **rejected** | ToS forbids third-party apps and automated re-posting of playlists/now-playing |
| E | `api.radioparadise.com` | not wired (uncertain) | no public API terms permitting reuse of its curated feed |
| E | *(a national broadcaster / admin-set host)* | proposal | admin-configurable allowlist, admin owns the per-station ToS check |

No Python dependency was added (A/B reuse `ytmusicapi`; C reuses the existing `httpx`).

## Contract

`GET /ut/v1/recommendations` (with `Recommendations`/`RecommendationShelf`/`SourceShelf` — a
`shelves` array was added for external sources), `GET /ut/v1/charts` (`Charts`), `GET /ut/v1/moods`
(`Moods`/`MoodCategory`) and `GET /ut/v1/moods/{moodId}` (`MoodTracks`) are now in
`contracts/openapi/ut-v1.yaml`, together with the new `charts` capability in `ServerInfo`. Items are
the existing `TrackItem`. All conform under schemathesis. This closes the reviewer's note that
`/ut/v1/recommendations` shipped undocumented.

## Android follow-up (not in this PR)

The client would add a "Recommended for you" / "Because you played …" / "Charts" section (SPEC §5
Listen Now tab, RF-11), fetching `/ut/v1/recommendations` and `/ut/v1/charts` through `:core:api`
(`TunesApi`) and rendering the `TrackItem`s with existing components. Server-side is complete for
v1; the client work is a separate PLAN task.
