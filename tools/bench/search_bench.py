# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`search3` latency with external results (SPEC §6: <= 2 s p95; PLAN T21).

    uv run --project server python tools/bench/search_bench.py --base http://127.0.0.1:18044 \
        --key-file KEY [--distinct 25] [--repeat 5] [--gap-s 3]

Against a server with `UT_FAKE_YOUTUBE=false` this reaches the REAL YouTube Music through the
server (ytmusicapi): keep it a small, polite sample. One `search3` costs three catalog requests
(songs, albums, artists), so the default gap of 3 s between searches keeps the average at
<= 1 request per second, and the defaults send 30 searches in all. `--distinct` searches use
queries never sent before in this run (cold TTL cache); `--repeat` then repeats some of them
(warm cache). The queries are plain words, no names of real people.

Prints, per search: latency, how many external (`yt:`, `ytalbum:`, `ytartist:`)
songs/albums/artists came back, and a summary with p50/p95/max for the cold and the warm
searches and how many cold searches came back without any external result (the 1.5 s budget
of `search_external_timeout_s` ran out or the catalog failed).
"""

import argparse
import statistics
import sys
import time
from pathlib import Path

import httpx

QUERIES = [
    "midnight drive", "summer rain", "golden hour", "ocean eyes", "slow dancing", "neon lights",
    "paper planes", "city of stars", "wild horses", "blue moon", "starlight", "heartbeat",
    "lost in the woods", "sunrise acoustic", "rainy day jazz", "piano lullaby", "desert road",
    "electric love", "northern lights", "dancing queen", "fireflies", "coffee shop", "orange sky",
    "silver lining", "late night radio", "first snow", "highway song", "violet hour",
    "morning bossa", "tidal wave",
]  # fmt: skip


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, round(pct / 100 * len(ordered) + 0.5) - 1))
    return ordered[rank]


def summary(label: str, values: list[float]) -> str:
    if not values:
        return f"{label}: no samples"
    return (
        f"{label}: n={len(values)} p50={statistics.median(values):.0f} ms"
        f" p95={percentile(values, 95):.0f} ms max={max(values):.0f} ms"
    )


def external(items: list[dict[str, object]]) -> int:
    prefixes = ("yt:", "ytalbum:", "ytartist:")
    return sum(1 for i in items if str(i.get("id", "")).startswith(prefixes))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="http://127.0.0.1:18044")
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--distinct", type=int, default=25)
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--gap-s", type=float, default=3.0)
    args = parser.parse_args()
    if args.distinct > len(QUERIES) or args.distinct + args.repeat > 30:
        parser.error("at most 30 searches in all (a polite sample)")
    key = args.key_file.read_text(encoding="utf-8").strip()
    client = httpx.Client(base_url=args.base, timeout=30)
    common = {"f": "json", "v": "1.16.1", "c": "ut-bench", "apiKey": key}
    plan = [(q, "cold") for q in QUERIES[: args.distinct]]
    plan += [(q, "warm") for q in QUERIES[: args.repeat]]
    times: dict[str, list[float]] = {"cold": [], "warm": []}
    library_only = 0
    for n, (query, kind) in enumerate(plan):
        if n:
            time.sleep(args.gap_s)
        params = {**common, "query": query, "artistCount": 5, "albumCount": 10, "songCount": 20}
        start = time.perf_counter()
        resp = client.get("/rest/search3", params=params)
        elapsed = (time.perf_counter() - start) * 1000
        resp.raise_for_status()
        result = resp.json()["subsonic-response"]["searchResult3"]
        ext = [external(result.get(k, [])) for k in ("song", "album", "artist")]
        if kind == "cold" and not any(ext):
            library_only += 1
        times[kind].append(elapsed)
        print(f"{kind} {query!r:<22} {elapsed:7.0f} ms  external songs/albums/artists"
              f" {ext[0]}/{ext[1]}/{ext[2]}", flush=True)  # fmt: skip
    print(summary("cold (first time each query)", times["cold"]))
    print(summary("warm (repeated, TTL cache)", times["warm"]))
    print(f"cold searches without any external result: {library_only}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
