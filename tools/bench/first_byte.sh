#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Server-side time to the first audio byte of `stream` (PLAN T21): what the phone waits for
# before ExoPlayer can buffer anything. Bench stack with the throttled worker only
# (tools/bench/compose.firstsound.yaml); it resets the external songs between rounds.
#   tools/bench/first_byte.sh KEY_FILE [PROJECT] [ROUNDS] [BASE]
# PROJECT is the compose project (default ut-bench), as in idle_ram.sh. The API key is read
# from KEY_FILE and handed to curl on standard input (`curl -K -`), never on a command line.
# External: the seven songs of the fake catalog, never played before (reset_external.py).
# Library: 30 random library songs (getAlbumList2 random + getAlbum).
# Percentiles are nearest-rank, like library_bench.py and search_bench.py.
set -euo pipefail

key=$(<"${1:?usage: first_byte.sh KEY_FILE [PROJECT] [ROUNDS] [BASE]}")
project=${2:-ut-bench}
rounds=${3:-2}
base=${4:-http://127.0.0.1:18044}
here=$(cd "$(dirname "$0")" && pwd)
external=(Fk2Lp9QwXa1 Rb8Tn3ZcYv0 Wq5Jd7HsKe2 Qx7Lm2pZ0aB Hm3Vx8Nq2Lp Tz9Kd4Wb7Rc Pa6Ye1Uo3Gs)

# curl reads its URL (which carries the key) from a config on stdin; printf is a builtin.
get() { # path-and-query (without the key), then curl options
  local path=$1
  shift
  printf 'url = "%s/rest/%s&v=1.16.1&c=ut-bench&apiKey=%s"\n' "$base" "$path" "$key" |
    curl -sS -K - "$@"
}

stats() { # label, then values in seconds on stdin
  sort -n | awk -v label="$1" '
    function rank(p,   r, i) { r = p / 100 * NR; i = int(r); if (i < r) i++; return i < 1 ? 1 : i }
    { v[NR] = $1 }
    END { printf "%s: n=%d p50=%.0f ms p95=%.0f ms max=%.0f ms\n", label, NR,
          v[rank(50)] * 1000, v[rank(95)] * 1000, v[NR] * 1000 }'
}

ttfb() { get "stream?id=$1" -o /dev/null -w '%{time_starttransfer}\n'; }

ext_times=()
for r in $(seq "$rounds"); do
  python3 "$here/reset_external.py" "$project" >/dev/null
  for id in "${external[@]}"; do
    t=$(ttfb "yt:$id")
    echo "external round $r yt:$id ttfb ${t}s" >&2
    ext_times+=("$t")
  done
done
printf '%s\n' "${ext_times[@]}" | stats "external (throttled fake, first play)"

albums=$(get "getAlbumList2?f=json&type=random&size=30" |
  python3 -c 'import json, sys; [print(a["id"]) for a in json.load(sys.stdin)["subsonic-response"]["albumList2"]["album"]]')
lib_times=()
for album in $albums; do
  song=$(get "getAlbum?f=json&id=$album" |
    python3 -c 'import json, sys; print(json.load(sys.stdin)["subsonic-response"]["album"]["song"][0]["id"])')
  lib_times+=("$(ttfb "$song")")
done
printf '%s\n' "${lib_times[@]}" | stats "library"
