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
if [[ -n "$(git status --porcelain)" ]]; then
  echo "Refusing to run on a dirty tree: the gates must test the committed HEAD. Commit or stash first." >&2
  exit 2
fi
git fetch -q origin master || { echo "cannot fetch origin/master" >&2; exit 2; }
base=$(git merge-base HEAD origin/master) || { echo "no merge base with origin/master" >&2; exit 2; }
on_master=false
[[ "$(git rev-parse HEAD)" == "$(git rev-parse origin/master)" ]] && on_master=true
log_dir=$(mktemp -d "${TMPDIR:-/tmp}/ut-ci-local.XXXXXX")
pg_name="ut-ci-local-pg-$$"
compose_project="ut-ci-local-$$"
cleanup() {
  docker stop "$pg_name" >/dev/null 2>&1 || true
  docker compose -p "$compose_project" -f server/compose.test.yaml down -v >/dev/null 2>&1 || true
}
trap cleanup EXIT
trap 'exit 130' INT TERM
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
known=(pr-title secrets store-texts server contracts android docker)
groups=(pr-title secrets store-texts)
if [[ "${1:-}" == --all ]] || { [[ $# -eq 0 ]] && $on_master; }; then
  groups=("${known[@]}")   # like a push to master in ci.yml: everything
elif [[ $# -gt 0 ]]; then
  for g in "$@"; do
    [[ " ${known[*]} " == *" $g "* ]] || { echo "unknown gate group: $g (known: ${known[*]})" >&2; exit 2; }
  done
  groups=("$@")
else
  changed=$(git diff --no-renames --name-only "$base"...HEAD)
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
pr_title() {
  # Same rule as .github/workflows/pr-title.yml (squash merges make the title the commit).
  local title err
  $on_master && { echo "on master: no PR title to check"; return 0; }
  if ! title=$(gh pr view --json title --jq .title 2>"$log_dir/gh.err"); then
    err=$(cat "$log_dir/gh.err")
    # Only "this branch has no PR" passes; a logged-out gh or no network must not.
    if grep -qi "no pull requests found" <<<"$err"; then
      echo "no PR for this branch: title not checked"; return 0
    fi
    echo "cannot read the PR title: $err" >&2; return 1
  fi
  echo "PR title: $title"
  if ! grep -qE '^(feat|fix|perf|refactor|test|docs|build|ci|chore|revert)(\([a-z0-9-]+\))?!?: [A-Za-z].+[^.]$' <<<"$title"; then
    echo "not a Conventional Commit title (type(scope)?: Subject, no trailing period)" >&2
    return 1
  fi
}

secrets() {
  # The commits this branch adds (like CI on a PR); the whole of master's history on master.
  # Worktrees keep their git data in the main checkout's common dir: mount it at the same path,
  # or gitleaks sees no repository and "passes" after scanning nothing.
  local range="$base..HEAD" common out expected
  $on_master && range="HEAD"
  common=$(cd "$(git rev-parse --git-common-dir)" && pwd)
  expected=$(git rev-list --count "$range")
  out=$(docker run --rm -v "$PWD:$PWD:ro" -v "$common:$common:ro" -w "$PWD" "$GITLEAKS_IMAGE" \
    git "$PWD" --redact --exit-code 1 "--log-opts=$range" 2>&1)
  local rc=$?
  printf '%s\n' "$out"
  (( rc == 0 )) || return $rc
  if (( expected > 0 )) && ! grep -qE "[1-9][0-9]* commits scanned" <<<"$out"; then
    echo "gitleaks scanned no commits but $expected were expected" >&2
    return 1
  fi
}

store_texts() {
  tools/tests/run.sh || return 1
  if [[ "$(git branch --show-current)" == release/* ]]; then
    tools/check-store-texts.sh --release
  else
    tools/check-store-texts.sh
  fi
}

server() {
  # The tagging golden tests skip without ffmpeg; CI installs it, so require it here too.
  command -v ffmpeg >/dev/null || { echo "ffmpeg is required (the tagging golden tests need it)" >&2; return 1; }
  (cd server && uv sync --locked && make check)
}

contracts() {
  local port rc ready=false
  port=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')
  docker run -d --rm --name "$pg_name" -e POSTGRES_PASSWORD=ci -e POSTGRES_DB=ultimatetunes \
    -p "127.0.0.1:$port:5432" "$POSTGRES_IMAGE" >/dev/null || return 1
  for _ in $(seq 60); do docker exec "$pg_name" pg_isready -U postgres -q && { ready=true; break; }; sleep 1; done
  $ready || { echo "PostgreSQL did not become ready in 60 s" >&2; docker stop "$pg_name" >/dev/null; return 1; }
  (cd server && uv sync --locked && UT_TEST_POSTGRES_URL="postgresql://postgres:ci@127.0.0.1:$port/ultimatetunes" make contracts)
  rc=$?
  docker stop "$pg_name" >/dev/null
  return $rc
}

android() {
  # --no-daemon: no Gradle daemon left behind (RAM).
  (cd android && ./gradlew --no-daemon check assembleDebug)
}

docker_gate() {
  local tag="ultimatetunes-server:ci-local" project="$compose_project" rc
  docker build -f server/Dockerfile -t "$tag" . || return 1
  docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v "$HOME/.cache/trivy:/root/.cache/trivy" \
    "$TRIVY_IMAGE" image --quiet --severity CRITICAL,HIGH --ignore-unfixed --exit-code 1 "$tag" || return 1
  docker compose -p "$project" -f server/compose.test.yaml up -d --build --wait || {
    docker compose -p "$project" -f server/compose.test.yaml down -v; return 1; }
  # The test stack publishes 127.0.0.1:8044; only one stack can use it at a time.
  curl -fsS http://127.0.0.1:8044/healthz && curl -fsS http://127.0.0.1:8044/readyz
  rc=$?
  docker compose -p "$project" -f server/compose.test.yaml down -v
  return $rc
}

want pr-title && run pr-title pr_title
want secrets && run secrets secrets
want store-texts && run store-texts store_texts
want server && run server server
want contracts && run contracts contracts
want android && run android android
want docker && run docker docker_gate

echo
(( ${#results[@]} > 0 )) || { echo "No gate ran." >&2; exit 2; }
printf '%s\n' "${results[@]}"
if (( fail )); then echo "Local CI: FAILED"; else echo "Local CI: green"; rm -rf "$log_dir"; fi
exit $fail
