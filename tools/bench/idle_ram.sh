#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Idle RAM of the api and the worker (SPEC §6: <= 200 MB together; PLAN T21).
# Samples `docker stats` (cgroup memory without page cache) of a running compose project.
#   tools/bench/idle_ram.sh [PROJECT] [SAMPLES] [INTERVAL_S]
# Start the stack first and let it settle, e.g.
#   docker compose -p ut-bench -f server/compose.test.yaml -f tools/bench/compose.bench.yaml up -d --wait
# Prints one line per sample and the mean and max per service and for both together, in MiB.
set -euo pipefail

project=${1:-ut-bench}
samples=${2:-10}
interval=${3:-3}

to_mib() { # "123.4MiB" | "1.2GiB" | "900KiB" -> MiB
  awk -v v="$1" 'BEGIN {
    n = v + 0; u = v; sub(/^[0-9.]+/, "", u)
    if (u == "GiB") n *= 1024; else if (u == "KiB") n /= 1024; else if (u == "B") n /= 1048576
    printf "%.1f", n }'
}

api="${project}-api-1"
worker="${project}-worker-1"
for c in "$api" "$worker"; do
  docker inspect "$c" >/dev/null 2>&1 || { echo "container $c is not running" >&2; exit 1; }
done

sum_api=0 sum_worker=0 max_api=0 max_worker=0 max_total=0
for i in $(seq "$samples"); do
  read -r a w < <(docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' "$api" "$worker" |
    awk -v api="$api" '{ split($2, m, "/"); if ($1 == api) a = m[1]; else w = m[1] } END { print a, w }')
  a=$(to_mib "$a") w=$(to_mib "$w")
  t=$(awk -v a="$a" -v w="$w" 'BEGIN { printf "%.1f", a + w }')
  echo "sample $i: api ${a} MiB, worker ${w} MiB, total ${t} MiB"
  read -r sum_api sum_worker max_api max_worker max_total < <(awk -v sa="$sum_api" -v sw="$sum_worker" \
    -v ma="$max_api" -v mw="$max_worker" -v mt="$max_total" -v a="$a" -v w="$w" -v t="$t" \
    'BEGIN { print sa + a, sw + w, (a > ma ? a : ma), (w > mw ? w : mw), (t > mt ? t : mt) }')
  (( i < samples )) && sleep "$interval"
done
awk -v n="$samples" -v sa="$sum_api" -v sw="$sum_worker" -v ma="$max_api" -v mw="$max_worker" \
  -v mt="$max_total" 'BEGIN {
    printf "mean: api %.1f MiB, worker %.1f MiB, total %.1f MiB\n", sa / n, sw / n, (sa + sw) / n
    printf "max:  api %.1f MiB, worker %.1f MiB, total %.1f MiB\n", ma, mw, mt }'
