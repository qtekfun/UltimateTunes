<!-- SPDX-FileCopyrightText: 2026 UltimateTunes contributors -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Music recommendations — design proposal

What the owner asked for: recommendations "based on what I listen to, from public platform
lists, national radios, etc." This document lays out the options, flags which ones would need a
**new outbound host or dependency** (forbidden until the owner approves, CLAUDE.md), and records
what is **implemented now** versus what stays a **ready-to-approve proposal**.

Hard rules this design keeps (CLAUDE.md, SPEC §6):

- The Android app talks only to the user's server. The server talks only to the hosts already
  allowlisted in CLAUDE.md. **No new host or dependency is added here.**
- No telemetry, no analytics, no non-free data source, and the user's listening history never
  leaves the server.

The baseline (option A) ships in this PR. Everything that would need a new host (options C–E) is
described precisely so the owner can approve a host before any of it is built.

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
| A | **Your own plays + favourites → existing YouTube Music radio** | **No** (reuses `ytmusicapi`) | Same grey area as the rest of the app (personal use, never offered to third parties); no extra data source | **Implemented in this PR** |
| B | **YouTube Music charts & moods** (`get_charts`, `get_mood_playlists`) | **No** (reuses `ytmusicapi`) | Same as A | **Proposed** — no new host, needs a small catalog addition; recommended as the next step |
| C | **ListenBrainz** recommendations / similar artists | **Yes** — `api.listenbrainz.org` | Free data (CC0), ToS-friendly, GPL-compatible | **Proposed, needs owner approval of the host** |
| D | **MusicBrainz / ListenBrainz "similar artists"** by MBID | **Partly** — MusicBrainz host is already approved for tagging; ListenBrainz is new | Free (CC0) | **Proposed, partial new host** |
| E | **National radio / public station playlists** (e.g. RadioParadise, SomaFM, or a station's public "now playing" API) | **Yes** — one new host per station | Varies per station; must be checked individually | **Proposed, needs owner approval per host** |

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

**Not implemented here** only because it is a larger, separate change (new catalog methods,
parsing, fakes) and the task scoped this PR to the no-contract-break baseline. It needs no owner
host approval — only a go-ahead to build it.

### C. ListenBrainz (proposed — needs a new host)

**Data source**: `api.listenbrainz.org` — collaborative, open recommendation data
(recommendation playlists, "similar artists/recordings"), tied to MusicBrainz IDs.

**New host**: **yes** — `api.listenbrainz.org` (HTTPS). Not currently allowlisted.

**Free-software/ToS**: ListenBrainz data is **CC0**; the API is free and GPL-compatible. It does
**not** require sending the user's listening history — read-only lookups (similar artists for an
MBID, curated recommendation playlists) are enough, so privacy is preserved. (SPEC §9 lists
ListenBrainz/Last.fm *scrobbling* as out of scope; this is read-only *recommendation lookup*, a
different use — still worth confirming with the owner.)

**Fit**: the server already stores `musicbrainz_recording_id` / artist MBIDs and already talks to
MusicBrainz during tagging. A ListenBrainz client would live behind a `Recommender` interface so
it is optional and off by default.

**Blocked on**: owner approval to add `api.listenbrainz.org` to the allowlist.

### D. MusicBrainz-based similarity (proposed — mostly existing host)

**Data source**: MusicBrainz relationships already reachable (`musicbrainz.org`, approved for
tagging). MusicBrainz alone has limited "similar artist" data; the richer "similar" signal lives
in ListenBrainz (option C), so D in practice folds into C.

**New host**: MusicBrainz itself is already approved; the useful similarity data needs
ListenBrainz (so, same approval as C).

### E. National radios / public station playlists (proposed — a new host per station)

**Data source**: public "now playing" / recent-tracks feeds some stations publish, e.g.
RadioParadise (`api.radioparadise.com`), SomaFM (`somafm.com`), or a national broadcaster's open
playlist API where one exists. Each gives a stream of recently-played tracks that can be matched
to YouTube Music and seeded like any other list.

**New host**: **yes — one per station**, each to be allowlisted explicitly.

**Free-software/ToS**: **must be checked per station.** Some publish open playlist data under
friendly terms (RadioParadise, SomaFM are community-friendly); many national broadcasters
restrict reuse or have no public API at all. No station is assumed safe; each needs its own ToS
check **and** owner approval of its host before anything is built.

**Fit**: behind the same optional `Recommender` interface as C, each station a small adapter that
produces seed tracks matched on YouTube Music (title/artist/duration, as playlist import does).

## What is implemented vs. proposed

- **Implemented now** (this PR, no new host/dependency, no contract break): option **A**,
  `GET /ut/v1/recommendations`, server-side.
- **Proposed, no host approval needed, just a go-ahead**: option **B** (YouTube Music charts and
  moods) — the recommended next step for "public / national lists".
- **Proposed, needs the owner to approve a new host first**: options **C/D** (ListenBrainz,
  `api.listenbrainz.org`) and **E** (per-station hosts, each with its own ToS check).

### Hosts to approve (exact names), if the owner wants to go beyond the baseline

| Option | Host to allowlist | Why | ToS note |
|--------|-------------------|-----|----------|
| C/D | `api.listenbrainz.org` | similar artists/recordings, recommendation playlists | CC0 data, free API, read-only (no history sent) |
| E | `api.radioparadise.com` | station recent-tracks feed | community-friendly; confirm current ToS |
| E | `somafm.com` | station recent-tracks feed | community-friendly; confirm current ToS |
| E | *(a specific national broadcaster)* | public playlist API | **check per broadcaster — many restrict reuse** |

No dependency additions are needed for A or B (both reuse `ytmusicapi`). C/D/E would reuse the
existing `httpx` client — still **no new Python dependency** — only the hosts above.

## Contract note

`GET /ut/v1/recommendations` is **additive** and is not yet in
`contracts/openapi/ut-v1.yaml` (contracts are frozen per wave; only the coordinator changes
them). Its items are `TrackItem`s, which the contract already defines. The proposed schema for
the coordinator to add:

```yaml
# paths:
  /ut/v1/recommendations:
    get:
      operationId: getRecommendations
      tags: [discovery]
      summary: Recommended songs from your plays and favourites
      description: >
        RF-06. New songs to discover, seeded from the caller's most-played and favourite songs
        into the YouTube Music watch playlist (like /ut/v1/radio). Charged to the caller's
        bucket. Empty when the caller has no plays or favourites.
      parameters:
        - { name: limit, in: query, required: false,
            schema: { type: integer, minimum: 1, maximum: 50, default: 20 } }
      responses:
        '200':
          description: Recommendation shelves (each may be empty).
          content:
            application/json:
              schema: { $ref: '#/components/schemas/Recommendations' }
# components.schemas:
    Recommendations:
      type: object
      required: [recommendedForYou, becauseYouPlayed]
      properties:
        recommendedForYou:
          type: array
          items: { $ref: '#/components/schemas/TrackItem' }
          maxItems: 50
          description: Songs the most seed-radios agree on, best first.
        becauseYouPlayed:
          type: array
          items: { $ref: '#/components/schemas/RecommendationShelf' }
          maxItems: 10
    RecommendationShelf:
      type: object
      required: [seed, items]
      properties:
        seed: { $ref: '#/components/schemas/TrackItem' }
        items:
          type: array
          items: { $ref: '#/components/schemas/TrackItem' }
          maxItems: 50
```

## Android follow-up (not in this PR)

The client would add a "Recommended for you" / "Because you played …" section (SPEC §5 Listen Now
tab, RF-11), fetching `/ut/v1/recommendations` through `:core:api` (`TunesApi`) and rendering the
`TrackItem`s with existing components. Server-side is complete for v1; the client work is a
separate PLAN task once the coordinator adds the endpoint to the contract.
