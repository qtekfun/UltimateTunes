#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# End-to-end suite (PLAN T20): brings up the test stack (fake YouTube, never a real download)
# from empty volumes, runs the server-side e2e (pytest over HTTP against the real containers)
# and, when a phone is named, the device-side e2e (instrumented test through `adb reverse`),
# then tears the stack down whatever happened.
#
#   tools/e2e/run.sh                     # server side only
#   UT_E2E_DEVICE=<adb serial> tools/e2e/run.sh   # + the device side on that phone
#
# Settings (env): UT_E2E_PORT (host port of the api, default 8044), UT_E2E_PROJECT (Compose
# project, default ut-e2e), UT_E2E_DEVICE (adb serial; empty = no device part), UT_E2E_ADB_LOCK
# (a file to `flock`, held for the whole device part, for a phone shared with other jobs),
# UT_E2E_KEEP=1 (leave the stack up at the end, to look around).
#
# The device part installs the debug app and its test APK (`installDebug installDebugAndroidTest`,
# never `connected*`, which would wipe the app on the author's phone) and maps the phone's
# 127.0.0.1:8044 to the stack (debug builds allow cleartext to 127.0.0.1 only). The test keeps
# its caches in its own directory and never touches the app's saved server.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PORT="${UT_E2E_PORT:-8044}"
PROJECT="${UT_E2E_PROJECT:-ut-e2e}"
DEVICE="${UT_E2E_DEVICE:-}"
LOCK="${UT_E2E_ADB_LOCK:-}"
URL="http://127.0.0.1:${PORT}"
DEVICE_PORT=8044
# The stack's throwaway admin (same values as server/tests/e2e/stack.py; never a real one).
ADMIN_USERNAME="e2eadmin"
ADMIN_PASSWORD="e2e-admin-password-not-a-secret"

compose() {
  docker compose -p "$PROJECT" \
    -f "$REPO/server/compose.test.yaml" -f "$REPO/tools/e2e/compose.e2e.yaml" "$@"
}

# Takes the shared-phone lock (when one is set) for the rest of this script: install, reverse,
# instrument and the reverse restore in the teardown all run under one hold, released at exit.
hold_phone() {
  if [[ -n "$LOCK" ]]; then
    exec 9>>"$LOCK"
    flock 9
  fi
}

# adb and Gradle never inherit the lock's descriptor: an adb server or a Kotlin daemon they
# start would otherwise keep the phone locked after this script ends.
adb_() { adb "$@" 9>&-; }

reversed=0
previous_reverse=""
teardown() {
  local status=$?
  if [[ "$reversed" == 1 ]]; then
    # Put back whatever mapped the phone's port before this run, or remove ours.
    if [[ -n "$previous_reverse" ]]; then
      adb_ -s "$DEVICE" reverse "tcp:${DEVICE_PORT}" "$previous_reverse" >/dev/null 2>&1 || true
    else
      adb_ -s "$DEVICE" reverse --remove "tcp:${DEVICE_PORT}" >/dev/null 2>&1 || true
    fi
  fi
  if [[ "$status" != 0 ]]; then
    echo "e2e: FAILED (exit $status); last stack logs:" >&2
    compose logs --no-color --tail 150 >&2 || true
  fi
  if [[ "${UT_E2E_KEEP:-0}" == 1 ]]; then
    echo "e2e: stack left up (UT_E2E_KEEP=1) at $URL; project $PROJECT"
  else
    compose down -v --remove-orphans >/dev/null 2>&1 || true
  fi
  exit "$status"
}
trap teardown EXIT
trap 'exit 130' INT TERM

echo "e2e: fresh stack $PROJECT on $URL"
compose down -v --remove-orphans >/dev/null 2>&1 || true
UT_E2E_PORT="$PORT" compose up --build --wait --detach

echo "e2e: admin account"
compose exec -T -e "UT_BOOTSTRAP_ADMIN_PASSWORD=${ADMIN_PASSWORD}" api \
  ultimatetunes bootstrap-admin "$ADMIN_USERNAME"

echo "e2e: server side"
# Coverage is not measured here: the code under test runs inside the containers, not in pytest
# (`make -C server check` keeps the coverage gate). Only the strict-markers option is kept.
(
  cd "$REPO/server"
  uv sync --locked --quiet
  UT_E2E=1 UT_E2E_URL="$URL" UT_E2E_PROJECT="$PROJECT" \
    uv run pytest tests/e2e -o "addopts=--strict-markers" -p no:cacheprovider -v
)

if [[ -z "$DEVICE" ]]; then
  echo "e2e: device side skipped (set UT_E2E_DEVICE to an adb serial)"
  exit 0
fi

echo "e2e: device side on $DEVICE"
key="$(
  curl -fsS -X POST "$URL/ut/v1/keys" -H 'Content-Type: application/json' \
    -d "{\"username\":\"${ADMIN_USERNAME}\",\"password\":\"${ADMIN_PASSWORD}\",\"name\":\"e2e phone\"}" |
    python3 -c 'import json, sys; print(json.load(sys.stdin)["secret"])'
)"
hold_phone
(
  cd "$REPO/android"
  ANDROID_SERIAL="$DEVICE" ./gradlew --no-daemon -q installDebug installDebugAndroidTest 9>&-
)
previous_reverse="$(
  adb_ -s "$DEVICE" reverse --list | awk -v port="tcp:${DEVICE_PORT}" '$2 == port { print $3 }'
)"
reversed=1
adb_ -s "$DEVICE" reverse "tcp:${DEVICE_PORT}" "tcp:${PORT}"
output="$(
  adb_ -s "$DEVICE" shell am instrument -w \
    -e package com.qtekfun.ultimatetunes.e2e \
    -e utE2eUrl "http://127.0.0.1:${DEVICE_PORT}" -e utE2eKey "$key" \
    com.qtekfun.ultimatetunes.test/com.qtekfun.ultimatetunes.HiltTestRunner
)"
echo "$output"
# `am instrument` exits 0 even when tests fail: read its verdict.
if ! grep -q '^OK (1 test)' <<<"$output"; then
  echo "e2e: device side failed" >&2
  exit 1
fi
echo "e2e: all green"
