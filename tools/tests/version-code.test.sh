#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# tools/version-code.sh follows versionCodeOf (android/build-logic VersionCode.kt and its test).
set -uo pipefail
source "$(dirname "$0")/lib.sh"
vc="$TOOLS/version-code.sh"

# Same cases as VersionCodeTest.
expect_out "0.0.0" 99 "$vc" 0.0.0
expect_out "0.0.1-rc.1 (first pre-release)" 101 "$vc" 0.0.1-rc.1
expect_out "0.1.0" 10099 "$vc" 0.1.0
expect_out "1.0.0-rc.1" 1000001 "$vc" 1.0.0-rc.1
expect_out "1.0.0-rc.98" 1000098 "$vc" 1.0.0-rc.98
expect_out "1.0.0" 1000099 "$vc" 1.0.0
expect_out "1.2.3" 1020399 "$vc" 1.2.3
expect_out "99.99.99" 99999999 "$vc" 99.99.99
expect_out "2099.99.99 (largest)" 2099999999 "$vc" 2099.99.99
expect_out "leading zeros are decimal, not octal" 1080999 "$vc" 1.08.09

# Ordering: candidates < final < next version.
a=$("$vc" 1.0.0-rc.98) b=$("$vc" 1.0.0) c=$("$vc" 1.0.1-rc.1)
if (( a < b && b < c )); then passes=$((passes + 1)); else echo "FAIL: ordering $a $b $c"; failures=$((failures + 1)); fi

expect_fail "no argument" "usage" "$vc"
expect_fail "two components" "bad version" "$vc" 1.0
expect_fail "v prefix" "bad version" "$vc" v1.0.0
expect_fail "other pre-release" "bad version" "$vc" 1.0.0-beta.1
expect_fail "rc without number" "bad version" "$vc" 1.0.0-rc
expect_fail "trailing newline text" "bad version" "$vc" "1.0.0 "
expect_fail "rc.0" "rc must be 1..98" "$vc" 1.0.0-rc.0
expect_fail "rc.99 collides with the final" "rc must be 1..98" "$vc" 1.0.0-rc.99
expect_fail "MINOR 100" "below 100" "$vc" 1.100.0
expect_fail "PATCH 100" "below 100" "$vc" 1.0.100
expect_fail "too large" "too large" "$vc" 2100.0.0
expect_fail "overflow" "too large" "$vc" 1.0.0-rc.99999999999999999999

finish
