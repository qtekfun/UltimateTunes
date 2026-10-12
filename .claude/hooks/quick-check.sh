#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# Stop: runs the fast gates of whatever changed since HEAD before Claude finishes.
# Exit 2 sends the failure back to Claude so it fixes it. The full gates run in CI.
input=$(cat)
cd "$CLAUDE_PROJECT_DIR" || exit 0
if echo "$input" | grep -q '"stop_hook_active": *true'; then exit 0; fi
changed=$( { git diff --name-only HEAD; git ls-files --others --exclude-standard; } 2>/dev/null )
[[ -z "$changed" ]] && exit 0
fail=0
if echo "$changed" | grep -qE '^server/.*\.(py|toml|sql)$|^contracts/' && [[ -f server/pyproject.toml ]] && command -v uv >/dev/null; then
  if ! out=$(cd server && uv run ruff check . 2>&1 && uv run ruff format --check . 2>&1 && uv run mypy 2>&1 && uv run pytest -q -x 2>&1); then
    echo "Server fast gates failed (ruff, mypy, pytest). Fix before finishing:" >&2
    echo "$out" | tail -60 >&2
    fail=1
  fi
fi
if echo "$changed" | grep -qE '^android/.*\.(kt|kts|xml|toml)$' && [[ -x android/gradlew ]]; then
  if ! out=$(cd android && ./gradlew -q ktlintCheck detekt testDebugUnitTest 2>&1); then
    echo "Android fast gates failed (ktlintCheck detekt testDebugUnitTest). Fix before finishing:" >&2
    echo "$out" | tail -60 >&2
    fail=1
  fi
fi
(( fail )) && exit 2
exit 0
