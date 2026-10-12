#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Server-side time to the first audio byte of `stream` (PLAN T21): what the phone waits for
# before ExoPlayer can buffer anything. Bench stack with the throttled worker only
# (tools/bench/compose.firstsound.yaml); it resets the external songs between rounds.
#   tools/bench/first_byte.sh KEY_FILE [ROUNDS] [BASE]
# External: the seven songs of the fake catalog, never played before (reset_external.py).
# Library: 30 random library songs (getAlbumList2 random + getAlbum).
set -euo pipefail

key=$(<"${1:?usage: first_byte.sh KEY_FILE [ROUNDS] [BASE]}")
rounds=${2:-2}
base=${3:-http://127.0.0.1:18044}
here=$(cd "$(dirname "$0")" && pwd)
q="v=1.16.1&c=ut-bench&apiKey=$key"
external=(Fk2Lp9QwXa1 Rb8Tn3ZcYv0 Wq5Jd7HsKe2 Qx7Lm2pZ0aB Hm3Vx8Nq2Lp Tz9Kd4Wb7Rc Pa6Ye1Uo3Gs)

stats() { # label, then values in seconds on stdin
  sort -n | awk -v label="$1" '{ v[NR] = $1 } END {
    p50 = v[int((NR + 1) / 2)]; i95 = int(0.95 * NR + 0.999); if (i95 < 1) i95 = 1
    printf "%s: n=%d p50=%.0f ms p95=%.0f ms max=%.0f ms\n", label, NR, p50 * 1000, v[i95] * 1000, v[NR] * 1000 }'
}

ttfb() { curl -sS -o /dev/null -w '%{time_starttransfer}\n' "$base/rest/stream?$q&id=$1"; }

ext_times=()
for r in $(seq "$rounds"); do
  docker exec -i ut-bench-api-1 python - <"$here/reset_external.py" >/dev/null
  for id in "${external[@]}"; do
    t=$(ttfb "yt:$id")
    echo "external round $r yt:$id ttfb ${t}s" >&2
    ext_times+=("$t")
  done
done
printf '%s\n' "${ext_times[@]}" | stats "external (throttled fake, first play)"

albums=$(curl -sS "$base/rest/getAlbumList2?$q&f=json&type=random&size=30" |
  python3 -c 'import json, sys; [print(a["id"]) for a in json.load(sys.stdin)["subsonic-response"]["albumList2"]["album"]]')
lib_times=()
for album in $albums; do
  song=$(curl -sS "$base/rest/getAlbum?$q&f=json&id=$album" |
    python3 -c 'import json, sys; print(json.load(sys.stdin)["subsonic-response"]["album"]["song"][0]["id"])')
  lib_times+=("$(ttfb "$song")")
done
printf '%s\n' "${lib_times[@]}" | stats "library"
