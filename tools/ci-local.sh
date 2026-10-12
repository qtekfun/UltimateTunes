#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Local CI: the same gates GitHub Actions ran (.github/workflows/ci.yml), on this machine, one
# after another to keep RAM low. GitHub Actions are disabled (no spending; SPEC §11).
#
#   tools/ci-local.sh            gates for what changed against origin/master (like ci.yml)
#   tools/ci-local.sh --all      every gate
#   tools/ci-local.sh server android docker   only those groups
#
# Groups: secrets, store-texts, server (make check), contracts (disposable PostgreSQL),
# android (gradle check assembleDebug), docker (build, Trivy, compose smoke test).
# A merge needs this green on the PR branch (merged with master) plus the independent review.
set -uo pipefail

cd "$(git rev-parse --show-toplevel)"
base=$(git merge-base HEAD origin/master 2>/dev/null || echo origin/master)
log_dir=$(mktemp -d "${TMPDIR:-/tmp}/ut-ci-local.XXXXXX")
declare -a results=()
fail=0

GITLEAKS_IMAGE=ghcr.io/gitleaks/gitleaks:v8.30.1
TRIVY_IMAGE=aquasec/trivy:0.65.0
POSTGRES_IMAGE=postgres:17

want() { [[ " ${groups[*]} " == *" $1 "* ]]; }

run() { # name, command...
  local name=$1; shift
  printf '== %s\n' "$name"
  if "$@" >"$log_dir/$name.log" 2>&1; then
    results+=("PASS  $name")
  else
    results+=("FAIL  $name  (log: $log_dir/$name.log)")
    tail -30 "$log_dir/$name.log"
    fail=1
  fi
}

# --- which groups ---------------------------------------------------------------------------
groups=(secrets store-texts)
if [[ $# -gt 0 && "$1" != --all ]]; then
  groups=("$@")
elif [[ "${1:-}" == --all ]]; then
  groups+=(server contracts android docker)
else
  changed=$( { git diff --name-only "$base"...HEAD; git diff --name-only; } | sort -u)
  shared='^(\.github/|VERSION$|tools/|\.claude/|\.gitleaks)'
  if grep -qE "^(server/|contracts/|\.dockerignore$)|$shared" <<<"$changed"; then
    groups+=(server contracts docker)
  fi
  if grep -qE "^(android/|contracts/openapi/)|$shared" <<<"$changed"; then
    groups+=(android)
  fi
fi
echo "Gates: ${groups[*]}  (base $(git rev-parse --short "$base"))"

# --- gates ----------------------------------------------------------------------------------
secrets() {
  # The commits this branch adds (like CI on a PR); the whole history on master.
  local range="--log-opts=$base..HEAD"
  [[ "$(git rev-parse HEAD)" == "$(git rev-parse "$base")" ]] && range=""
  docker run --rm -v "$PWD:/repo:ro" "$GITLEAKS_IMAGE" git /repo --redact --exit-code 1 $range
}

store_texts() {
  tools/tests/run.sh
  if [[ "$(git branch --show-current)" == release/* ]]; then
    tools/check-store-texts.sh --release
  else
    tools/check-store-texts.sh
  fi
}

server() { (cd server && uv sync --locked && make check); }

contracts() {
  local port name rc
  port=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')
  name="ut-ci-local-pg-$$"
  docker run -d --rm --name "$name" -e POSTGRES_PASSWORD=ci -e POSTGRES_DB=ultimatetunes \
    -p "127.0.0.1:$port:5432" "$POSTGRES_IMAGE" >/dev/null || return 1
  for _ in $(seq 60); do docker exec "$name" pg_isready -U postgres -q && break; sleep 1; done
  (cd server && UT_TEST_POSTGRES_URL="postgresql://postgres:ci@127.0.0.1:$port/ultimatetunes" make contracts)
  rc=$?
  docker stop "$name" >/dev/null
  return $rc
}

android() {
  # --no-daemon: no Gradle daemon left behind (RAM).
  (cd android && ./gradlew --no-daemon check assembleDebug)
}

docker_gate() {
  local tag="ultimatetunes-server:ci-local" project="ut-ci-local-$$" rc
  docker build -f server/Dockerfile -t "$tag" . || return 1
  docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v "$HOME/.cache/trivy:/root/.cache/" \
    "$TRIVY_IMAGE" image --quiet --severity CRITICAL,HIGH --ignore-unfixed --exit-code 1 "$tag" || return 1
  docker compose -p "$project" -f server/compose.test.yaml up -d --build --wait || {
    docker compose -p "$project" -f server/compose.test.yaml down -v; return 1; }
  # The test stack publishes 127.0.0.1:8044; only one stack can use it at a time.
  curl -fsS http://127.0.0.1:8044/healthz && curl -fsS http://127.0.0.1:8044/readyz
  rc=$?
  docker compose -p "$project" -f server/compose.test.yaml down -v
  return $rc
}

want secrets && run secrets secrets
want store-texts && run store-texts store_texts
want server && run server server
want contracts && run contracts contracts
want android && run android android
want docker && run docker docker_gate

echo
printf '%s\n' "${results[@]}"
if (( fail )); then echo "Local CI: FAILED"; else echo "Local CI: green"; rm -rf "$log_dir"; fi
exit $fail
