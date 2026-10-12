# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Latency of the library browse endpoints against a running server (PLAN T21).

    uv run --project server python tools/bench/library_bench.py --base http://127.0.0.1:18044 \
        --key-file KEY [--queries OUT_DIR/bench-queries.txt] [--samples 30] [--budget-s 120]
        [--tracks 50000 --albums 5000]

Sends OpenSubsonic requests one after another (one client, like the phone), after two warm-up
calls per endpoint, and prints p50/p95/max in milliseconds and the response size per endpoint.
An endpoint stops early once it has used `--budget-s` seconds (at least 5 samples), so a slow
one does not hold the run for an hour. Library-only search needs the server started with
`UT_EXTERNAL_SEARCH=false`. The API key is read from a file so it never shows in `ps`.
"""

import argparse
import math
import random
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

Params = dict[str, str | int]


def percentile(values: list[float], pct: float) -> float:
    """Nearest rank: the smallest sample with at least `pct` % of the samples at or below it
    (p50 included; the same definition as first_byte.sh and docs/measurements.md)."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(pct / 100 * len(ordered)) - 1)]


class Bench:
    def __init__(self, base: str, key: str, samples: int, budget_s: float) -> None:
        self.client = httpx.Client(base_url=base, timeout=300)
        self.common: Params = {"f": "json", "v": "1.16.1", "c": "ut-bench", "apiKey": key}
        self.samples = samples
        self.budget_s = budget_s
        self.rows: list[tuple[str, int, float, float, float, int]] = []

    def get(self, method: str, params: Params) -> tuple[float, dict[str, Any], int]:
        start = time.perf_counter()
        resp = self.client.get(f"/rest/{method}", params={**self.common, **params})
        elapsed = (time.perf_counter() - start) * 1000
        resp.raise_for_status()
        body = resp.json()["subsonic-response"]
        if body.get("status") != "ok":
            raise RuntimeError(f"{method}: {body.get('error')}")
        return elapsed, body, len(resp.content)

    def run(self, label: str, method: str, make: Callable[[], Params]) -> None:
        for _ in range(2):
            self.get(method, make())
        times: list[float] = []
        size = 0
        began = time.perf_counter()
        while len(times) < self.samples:
            elapsed, _, size = self.get(method, make())
            times.append(elapsed)
            if len(times) >= 5 and time.perf_counter() - began > self.budget_s:
                break
        row = (
            label,
            len(times),
            percentile(times, 50),
            percentile(times, 95),
            max(times),
            size,
        )
        self.rows.append(row)
        print(f"{label:<44} n={row[1]:<3} p50={row[2]:8.1f} p95={row[3]:8.1f} max={row[4]:8.1f}"
              f" bytes={size}", flush=True)  # fmt: skip


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="http://127.0.0.1:18044")
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--queries", type=Path)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--budget-s", type=float, default=120.0)
    parser.add_argument("--tracks", type=int, default=50_000, help="songs in the library")
    parser.add_argument("--albums", type=int, default=5_000, help="albums in the library")
    parser.add_argument("--only", help="comma-separated labels prefixes to run")
    args = parser.parse_args()
    key = args.key_file.read_text(encoding="utf-8").strip()
    bench = Bench(args.base, key, args.samples, args.budget_s)
    rng = random.Random(21)  # noqa: S311 - benchmark sampling, not security

    _, body, _ = bench.get("getAlbumList2", {"type": "alphabeticalByName", "size": 500})
    album_ids = [a["id"] for a in body["albumList2"]["album"]]
    artist_ids = sorted({a["artistId"] for a in body["albumList2"]["album"]})
    total, albums_total = args.tracks, args.albums
    queries = (
        [q for q in args.queries.read_text(encoding="utf-8").split() if q]
        if args.queries
        else ["Lantern", "Harbour", "Echo", "Moon"]
    )

    def offset(size: int) -> int:
        return rng.randrange(0, max(1, albums_total - size))

    cases: list[tuple[str, str, Callable[[], Params]]] = [
        ("getArtists", "getArtists", dict),
        ("getAlbumList2 alphabeticalByName 50 @rand", "getAlbumList2",
         lambda: {"type": "alphabeticalByName", "size": 50, "offset": offset(50)}),
        ("getAlbumList2 newest 50 @0", "getAlbumList2",
         lambda: {"type": "newest", "size": 50}),
        ("getAlbumList2 random 50", "getAlbumList2", lambda: {"type": "random", "size": 50}),
        ("getAlbum (10 songs)", "getAlbum", lambda: {"id": rng.choice(album_ids)}),
        ("getArtist", "getArtist", lambda: {"id": rng.choice(artist_ids)}),
        ("search3 library-only (20/20/20)", "search3",
         lambda: {"query": rng.choice(queries), "artistCount": 20, "albumCount": 20,
                  "songCount": 20}),
        ("search3 empty query 500 songs @rand (sync)", "search3",
         lambda: {"query": "", "artistCount": 0, "albumCount": 0, "songCount": 500,
                  "songOffset": rng.randrange(0, max(1, total - 500))}),
    ]  # fmt: skip
    only = [o.strip() for o in args.only.split(",")] if args.only else None
    for label, method, make in cases:
        if only and not any(label.startswith(o) for o in only):
            continue
        bench.run(label, method, make)
    return 0


if __name__ == "__main__":
    sys.exit(main())
