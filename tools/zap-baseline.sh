#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# OWASP ZAP baseline scan (spider + passive rules, no attacks) against the compose test stack
# (server/compose.test.yaml: fake YouTube, no real downloads, nothing persistent). PLAN T22.
#
#   tools/zap-baseline.sh [output dir]      default: server/reports/zap (git-ignored)
#
# Builds and starts the stack under its own project name, joins ZAP to the stack's network and
# scans the client listener (api:8044): the site and panel, then one URL of each API. The internal listener (api:8045) answers only
# /healthz and the token-protected /internal/v1 (server/tests/test_listeners.py). Rules ZAP
# should not apply here, each with its reason, are in tools/zap/baseline.conf (site and panel)
# and tools/zap/baseline-api.conf (the APIs). Exit code: 0 clean, 1 any FAIL or WARN left, 2 the
# scan could not run. The stack is always removed afterwards.
set -uo pipefail

# zaproxy/zap-stable 2.17.0 (multi-arch index digest). Bump the digest and the version together.
ZAP_IMAGE=zaproxy/zap-stable@sha256:7aaa659b0d43078febd82e29bad112285c370727e86ab8340444220e17d9f0d2
SPIDER_MINUTES=${ZAP_SPIDER_MINUTES:-2}

cd "$(git rev-parse --show-toplevel)"
out=$(realpath -m "${1:-server/reports/zap}")
project="ut-zap-$$"
# ZAP reaches the api over the stack's network, so nothing is published on the host (another
# stack, e.g. the e2e tests, may hold 127.0.0.1:8044).
unpublish=$(mktemp "${TMPDIR:-/tmp}/ut-zap-compose.XXXXXX.yaml")
printf 'services:\n  api:\n    ports: !reset []\n' >"$unpublish"
compose=(docker compose -p "$project" -f server/compose.test.yaml -f "$unpublish")
cleanup() { "${compose[@]}" down -v >/dev/null 2>&1 || true; rm -f "$unpublish"; }
trap cleanup EXIT
trap 'exit 130' INT TERM

mkdir -p "$out"
# ZAP runs as its own user (uid 1000) and writes its reports into the mounted directory.
chmod 0777 "$out"
cp tools/zap/baseline.conf tools/zap/baseline-api.conf "$out/"
chmod 0644 "$out/baseline.conf" "$out/baseline-api.conf"

"${compose[@]}" up -d --build --wait || { echo "the test stack did not start" >&2; exit 2; }

# The landing page and the panel (spidered), then the two APIs, which nothing links to:
# answers without credentials (OpenSubsonic error envelope, RFC 9457 problem).
targets=(
  "site|baseline.conf|http://api:8044/"
  "rest|baseline-api.conf|http://api:8044/rest/ping.view?f=json"
  "ut|baseline-api.conf|http://api:8044/ut/v1/server"
)
worst=0
for entry in "${targets[@]}"; do
  IFS='|' read -r name conf url <<<"$entry"
  echo "== $name: $url"
  docker run --rm --network "${project}_default" \
    --user 1000:1000 \
    --cap-drop ALL --security-opt no-new-privileges:true \
    -v "$out:/zap/wrk:rw" \
    "$ZAP_IMAGE" zap-baseline.py \
    -t "$url" \
    -m "$SPIDER_MINUTES" \
    -c "$conf" \
    -r "zap-$name.html" -J "zap-$name.json" -w "zap-$name.md" \
    -s
  rc=$?
  case $rc in
    0) ;;
    1|2) (( worst < 1 )) && worst=1 ;;
    *) worst=2 ;;
  esac
done

echo
echo "Reports: $out/zap-{site,rest,ut}.{html,json,md}"
case $worst in
  0) echo "ZAP baseline: clean"; exit 0 ;;
  1) echo "ZAP baseline: findings left (FAIL or WARN); see the reports" >&2; exit 1 ;;
  *) echo "ZAP baseline: a scan did not complete" >&2; exit 2 ;;
esac
