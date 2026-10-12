# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Tiny assertion helpers for the plain-bash tests of tools/ (sourced, not executed).
# Each test file sources this, calls the helpers, and ends with `finish`.

TOOLS=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
failures=0
passes=0

# expect_out "name" "expected stdout" cmd args...   (command must succeed)
expect_out() {
  local name=$1 want=$2 got
  shift 2
  if got=$("$@" 2>/dev/null) && [[ "$got" == "$want" ]]; then
    passes=$((passes + 1))
  else
    echo "FAIL: $name: expected '$want', got '${got:-}' (exit $?)"
    failures=$((failures + 1))
  fi
}

# expect_fail "name" "substring of stderr+stdout" cmd args...   (command must fail)
expect_fail() {
  local name=$1 want=$2 got
  shift 2
  if got=$("$@" 2>&1); then
    echo "FAIL: $name: expected a failure, it succeeded with '$got'"
    failures=$((failures + 1))
  elif [[ "$got" != *"$want"* ]]; then
    echo "FAIL: $name: expected the message to contain '$want', got '$got'"
    failures=$((failures + 1))
  else
    passes=$((passes + 1))
  fi
}

finish() {
  echo "$(basename "$0"): $passes passed, $failures failed"
  (( failures == 0 ))
}
