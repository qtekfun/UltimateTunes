<!--
SPDX-FileCopyrightText: 2026 UltimateTunes contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Measurements (PLAN T21)

These are the SPEC §6 targets, measured on 2026-10-12 against `master` at `91366b8` (T18). The scripts are in `tools/bench/`, so anyone can rerun them. No real music was used and nothing was downloaded from YouTube. The only real-network part is a polite sample of 30 searches against YouTube Music, sent through the server (ytmusicapi from the author's home IP, approved for T21).

**Percentiles** are nearest-rank everywhere (scripts and tables): p*N* is the ⌈N/100 · n⌉-th smallest sample, p50 included, so a p95 over 30 samples is the 29th.

## Summary

| SPEC §6 target | Result | Verdict |
| --- | --- | --- |
| Idle RAM, api + worker ≤ 200 MB | **92 MiB** just after start (fake or real config). **143 MiB** after real searches. **158 MiB** after browsing the 50,000-track library | Met |
| `search3` with external results ≤ 2 s p95 | Real YouTube Music, cold cache: **722 ms p50 / 1,039 ms p95**, max 1,677 ms (n = 25). Warm TTL cache: **195 / 256 ms** (n = 5) | Met |
| Smooth browse with 50,000 tracks | **As shipped:** `getArtists` **18.1 s p50 / 18.5 s p95**; library-only `search3` 66 ms p50 / **690 ms p95**; empty-query `search3` sync page 212 / 253 ms; every other endpoint ≤ 90 ms p95. **After `ANALYZE`** (issue #54): every endpoint ≤ 162 ms p95, `getArtists` 43 / 46 ms | **Not met** as shipped; met once #54 is fixed |
| First sound, library track ≤ 1 s | Server time to first audio byte **12 ms p50 / 18 ms p95** as shipped (9 / 10 ms after `ANALYZE`). On the phone: **not measured** (see below) | Server side met. Phone pending |
| First sound, external track ≤ 5 s | Server time to first audio byte **3.0 s p50 / 3.4 s p95** (second run: 2.6 / 3.6 s), with a modelled YouTube that gives its first byte after 1.8 s. On the phone: **not measured** | Server side met with ~1.6 s left for the client. The idle worker's 2 s poll costs ~1 s of it (issue #55) |

## Machine and setup

- **Host:** Intel Core Ultra 7 265U (14 threads), 30 GB RAM, Fedora 44 (kernel 7.2.9), btrfs on LUKS. Docker 29.9.0 with Compose v5.6.0. The image's SQLite is 3.46.1.
- **Stack:** the test stack (`server/compose.test.yaml`) plus `tools/bench/compose.bench.yaml`. That file uses its own project, host port 18044 and image tag, so it can run next to another stack. It logs at INFO, and the canary and the yt-dlp self-update are off, because both would download. Containers are hardened as in production: read-only root, `cap_drop: ALL`, non-root.
  ```sh
  docker compose -p ut-bench -f server/compose.test.yaml -f tools/bench/compose.bench.yaml up -d --build --wait
  ```
- **Accounts:** an admin is created with `ultimatetunes bootstrap-admin`, with the password read on standard input from a mode-600 file. An API key comes from `POST /ut/v1/keys`. The scripts read the key from a file and never put it on a command line.

## 1. Idle RAM (api + worker)

**Method:** `tools/bench/idle_ram.sh ut-bench 10 3` takes 10 `docker stats` samples, 3 s apart, once the stack has been up for 45–60 s. `docker stats` reports cgroup memory minus inactive page cache. Below, `RSS` is `VmRSS` of the main process.

| State | api | worker | Total (mean of 10, max) |
| --- | --- | --- | --- |
| Fake config (`UT_FAKE_YOUTUBE=true`), empty library, just started | 55.0 MiB | 36.7 MiB | **91.7 MiB** (max 92.2) |
| Real config (`UT_FAKE_YOUTUBE=false`, no request yet), empty library | 55.4 MiB | 36.9 MiB | **92.3 MiB** (max 93.5) |
| Real config after 30 real `search3` calls, 50,000-track library | 106.0 MiB (RSS 123 MiB) | 37.1 MiB (RSS 53 MiB) | **143.1 MiB** (max 143.5) |
| Fake config after the whole browse benchmark, 50,000-track library | 121.2 MiB (RSS 81 MiB, anon 64 MiB; the rest is DB page cache) | 37.2 MiB | **158.4 MiB** (max 158.7) |

Notes:
- The idle worker runs no tool. A real job adds yt-dlp (~65 MB) and, on the fallback client, a short-lived Deno process (~330 MB) (spike T03c). Those are per job, not idle.
- After the browse run, most of the api's growth is SQLite page cache of the 44 MB database (active file pages), which the kernel can reclaim. Process anonymous memory stayed at 64 MiB.
- **Watch out when measuring:** files written to the container's `/tmp` tmpfs count as `shmem` in `docker stats`. One stray 44 MB copy there briefly read as 200 MiB.

## 2. Library browse with 50,000 tracks

**Library:** `tools/bench/gen_library.py OUT_DIR --tracks 50000` generates 2,500 invented artists, 5,000 albums (10 tracks each) and 50,000 files. Each file is the 2 s CC0 silent Opus clip with invented Vorbis tags, about 200 MB on disk, in `OUT_DIR/music`, plus `OUT_DIR/bench-queries.txt` for the search rows. Generation takes 5 s. The files are copied into the `music` volume (`tar | docker exec -i … tar -x`) and registered with `ultimatetunes scan-library` inside the api container, as an admin would do it.

| Step | Result |
| --- | --- |
| First scan (50,000 new files) | **7 min 44 s**, and 7 min 45 s on a second fresh stack: about 108 files/s and 9 ms per file. Peak RSS 32 MB |
| Rescan, nothing changed | **4.3 s** |
| Database size | **43.7 MB** (`ultimatetunes.db`), plus a 4.3 MB WAL |

**Latency method:** `tools/bench/library_bench.py --key-file KEY --queries OUT_DIR/bench-queries.txt --samples 30 --budget-s 90`. It uses one HTTP client, sends one request at a time (like the phone), makes 2 warm-up calls per endpoint, and picks a random offset or id per sample. The search3 rows use `UT_EXTERNAL_SEARCH=false`, which makes them library-only. Times are milliseconds on the host, client included.

The two columns come from the same stack and data, one right after the other: first as shipped, then after one `ANALYZE` run in the container (the fix proposed in #54).

| Endpoint | As shipped (no statistics): p50 / p95 / max | After `ANALYZE` (#54): p50 / p95 / max | Response size |
| --- | --- | --- | --- |
| `getArtists` (all 2,500) | **18,073 / 18,516 / 18,516** (n = 5, budget cut) | **42.9 / 45.9 / 46.9** | 359 KB |
| `getAlbumList2` alphabeticalByName, 50, random offset | 87.3 / 89.7 / 90.3 | 81.6 / 84.2 / 85.8 | 25 KB |
| `getAlbumList2` newest, 50 | 86.1 / 87.5 / 94.3 | 75.6 / 83.7 / 85.4 | 25 KB |
| `getAlbumList2` random, 50 | 81.5 / 85.0 / 86.6 | 71.1 / 74.5 / 77.3 | 25 KB |
| `getAlbum` (10 songs) | 24.3 / 26.3 / 28.7 | 8.8 / 9.8 / 9.8 | 10 KB |
| `getArtist` | 29.2 / 35.9 / 36.8 | 8.6 / 9.8 / 9.9 | 1.3 KB |
| `search3` library-only, 20/20/20 | 66.3 / **689.9** / 702.2 | 120.2 / 134.3 / 135.2 | up to ~25 KB |
| `search3` empty query, 500 songs, random offset (client sync) | 212.4 / 252.7 / 253.5 | 94.5 / 161.8 / 164.2 | 498 KB |

An earlier run on another fresh stack (p50 then computed as the median) agrees within ~10 %, except `getArtists` at 19.6 s p50 / 23.5 s p95 as shipped.

Findings:
- **`getArtists` is O(albums × tracks)** (issue #54, label `perf`). Nothing ever runs `ANALYZE`, so SQLite has no statistics. It then resolves `EXISTS (SELECT 1 FROM tracks WHERE album_id = ? AND status = 'ready')` through `ix_tracks_status` (every track is `ready`) instead of `ix_tracks_album`. A single `ANALYZE` fixes it (21.4 s → 25 ms for the bare query). The fix belongs in the SQLite driver (`PRAGMA optimize`) and at the end of `scan-library`/`migrate`, which is outside T21's paths. The search3 artist query has the same shape, which explains its library-only p95 of 690 ms as shipped. After `ANALYZE` its p50 rises from 66 to 120 ms while its p95 drops from 690 to 134 ms: the planner trades a few fast queries for no slow ones.
- `getAlbumList2` aggregates every album on each call (~80 ms). That is fine for 50,000 tracks. A denormalised count would only matter well beyond that size.
- The first scan, at ~9 ms per file, has one transaction per file. That is acceptable for a one-off import (≈ 8 min for 50,000 files). It is noted here, not filed: SPEC sets no scan target.

## 3. `search3` with external results

**Method:** `tools/bench/search_bench.py --key-file KEY` (it refuses more than 30 searches or a gap under 1 s) runs against the stack with `UT_FAKE_YOUTUBE=false`, so the server calls the **real YouTube Music** through ytmusicapi from the home IP. The 50,000-track library is in place, and the defaults are those of `SearchSettings`: a 1.5 s external budget, 3 threads, and a 2 req/s bucket. The sample is 25 distinct plain-word queries (no names of real people), then 5 of them repeated. That is 30 searches, 3 s apart. One search3 makes 3 catalog requests (songs, albums, artists), so the average is ≤ 1 request/s. The search asks for 20 songs, 10 albums and 5 artists.

| Searches | p50 | p95 | max |
| --- | --- | --- | --- |
| Cold (first time each query), n = 25 | **722 ms** | **1,039 ms** | 1,677 ms |
| Warm (repeated, TTL cache), n = 5 | **195 ms** | **256 ms** | 256 ms |

- 25 of 25 cold searches returned external results. The **very first search after start** returned albums and artists but **no external songs**: the songs call missed the 1.5 s budget while the YTMusic session was still cold. It answered with library songs only and filled the cache, so a repeat showed them. A catalog warm-up when the api starts would hide this. That is a minor finding, not filed.
- No 429, bot check or block was seen.

## 4. First sound

### Server side (measured)

**Method:** `tools/bench/first_byte.sh KEY_FILE ut-bench 2` measures curl's time to the first audio byte of `/rest/stream`. That is everything the phone waits for before ExoPlayer can buffer.

- **External:** the stack runs with `tools/bench/compose.firstsound.yaml`. Its worker is the production loop (`build_worker`: the same claim, progress reports, streaming while downloading, archive and tagging), with only the downloader replaced by `tools/bench/throttled_worker.py`. That downloader serves a generated 240 s, 128 kbit/s Opus tone (4.6 MB, ffmpeg `sine`, no real music) as follows:
  - **Assumption:** the first byte comes **1.8 s** after the job starts. That is yt-dlp's default-client extraction (1.5–1.8 s) plus googlevideo's 30–80 ms to headers, both measured in spike T03c.
  - **Assumption:** the rest arrives at a throttled **1 MB/s**, far below the home link and ~60× the audio bitrate.
  - Progress is reported every 0.25 s, with the exact size known from the first report.
  - Each round starts from never-played songs: `reset_external.py PROJECT` forgets the 7 fake-catalog songs.
- **Library:** 30 random songs of the 50,000-track library.

| Track | n | p50 | p95 | max |
| --- | --- | --- | --- | --- |
| External, first play (modelled YouTube: 1.8 s to first byte, 1 MB/s), run 1 | 14 | **3,004 ms** | **3,435 ms** | 3,435 ms |
| External, same, run 2 (after the review fixes; database analysed) | 14 | **2,583 ms** | **3,625 ms** | 3,625 ms |
| Library, run 1 (as shipped) | 30 | **12 ms** | **18 ms** | 22 ms |
| Library, run 2 (after `ANALYZE`) | 30 | **9 ms** | **10 ms** | 13 ms |

The spread between the two external runs is the claim poll below: where in its 2 s cycle each request lands.

That leaves ~0.8–1.8 s between the 1.8 s modelled YouTube time and the first byte. Most of it is the **idle worker's claim poll**: every 2 s, with an immediate `204`, so 0–2 s and ≈ 1 s on average. The ≤ 0.25 s progress cadence adds the rest. Issue #55 proposes a long-poll or wake-up claim. On the `web_embedded` + Deno fallback (3.7–3.8 s extraction), the server-side first byte would be ≈ 5 s, which misses the target before the client even starts. That makes #55 and the default-client path matter.

### On the phone (not measured)

The plan: debug build of `master` on the author's Pixel 8 (Android 17, CP3A.260905.009), connected to the bench stack through `adb reverse tcp:18044 tcp:18044`. Time runs from the tap on a song row (device clock) to the first audio, read from logcat timestamps. The app does not install a Media3 `EventLogger`, so the marker is system_server's `MediaSessionService` `PlaybackState {state=PLAYING(3)}`.

**Blocked:** on that day every `MediaCodec` creation on the phone crashed natively. The crash was a SIGSEGV in `libstagefright.so` at `VideoRenderQualityTracker::Configuration::getFromServerConfigurableFlags`, reached from `MediaCodec::MediaCodec`. It hit the system MediaProvider (crash loop, 30+ tombstones) as well as our app's `ExoPlayer:Playback` thread as soon as it created the Opus decoder. This is a platform state, not an app bug, and a phone reboot (by the author) is needed before the measurement can run. Rules for that run: never `connected*`, never reboot from scripts, take `flock` on the shared phone lock.

**Estimate until then:** server first byte plus ExoPlayer start-up. ExoPlayer needs `bufferForPlaybackMs` of 2.5 s of audio, which is ~40 KB at 128 kbit/s, so less than 50 ms of transfer at the modelled rate, and typically 100–300 ms to prepare a decoder. That gives a library track ≈ 0.2–0.4 s (target ≤ 1 s) and an external track ≈ 3.2–3.7 s (target ≤ 5 s). These are estimates, not measurements.

## Rerunning

```sh
B=tools/bench; W=$(mktemp -d); C="docker compose -p ut-bench -f server/compose.test.yaml -f $B/compose.bench.yaml"
UT_EXTERNAL_SEARCH=false $C up -d --build --wait
uv run --project server python $B/gen_library.py "$W/lib"        # $W/lib/music + $W/lib/bench-queries.txt
tar -C "$W/lib/music" -cf - . | docker exec -i ut-bench-api-1 tar -C /music -xf - --no-same-owner
time docker exec ut-bench-api-1 ultimatetunes scan-library
(umask 077; head -c 24 /dev/urandom | base64 | tr -d '/+=' > "$W/admin.pw")   # mode 600
docker exec -i ut-bench-api-1 ultimatetunes bootstrap-admin bench < "$W/admin.pw"   # password on stdin
python3 -c 'import json, sys; print(json.dumps({"username": "bench", "name": "bench",
  "password": open(sys.argv[1]).read().strip()}))' "$W/admin.pw" |
  curl -s -X POST localhost:18044/ut/v1/keys -H 'content-type: application/json' --data-binary @- |
  python3 -c 'import json, sys; print(json.load(sys.stdin)["secret"])' > "$W/key"
uv run --project server python $B/library_bench.py --key-file "$W/key" --queries "$W/lib/bench-queries.txt"
$B/idle_ram.sh ut-bench
UT_FAKE_YOUTUBE=false $C up -d --wait     # real YouTube Music: a small sample only
uv run --project server python $B/search_bench.py --key-file "$W/key"
mkdir -p "$W/audio" && ffmpeg -f lavfi -i sine=frequency=440:duration=240:sample_rate=48000 \
  -af volume=0.2 -c:a libopus -b:a 128k "$W/audio/tone.opus"
UT_BENCH_AUDIO_DIR="$W/audio" $C -f $B/compose.firstsound.yaml up -d --wait
$B/first_byte.sh "$W/key" ut-bench 2
UT_BENCH_AUDIO_DIR="$W/audio" $C -f $B/compose.firstsound.yaml down -v
rm -rf "$W"
```
