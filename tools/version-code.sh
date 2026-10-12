#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# SemVer[-rc.N] -> Android versionCode: (MAJOR*10000 + MINOR*100 + PATCH)*100 + N, N = 99 for finals.
# 1.0.0-rc.1 -> 1000001, 1.0.0 -> 1000099. Same rules as versionCodeOf in
# android/build-logic (VersionCode.kt): MINOR and PATCH below 100, rc 1..98, code <= 2100000000.
# Tested by tools/tests/version-code.test.sh.
set -euo pipefail
v=${1:?usage: tools/version-code.sh X.Y.Z[-rc.N]}
# No component longer than 9 digits, so the arithmetic below cannot overflow.
[[ ! "$v" =~ [0-9]{10} ]] || { echo "version code too large: $v" >&2; exit 1; }
[[ "$v" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)(-rc\.([0-9]+))?$ ]] || { echo "bad version: $v" >&2; exit 1; }
# 10# : base 10 even with leading zeros (bash reads 08 as octal otherwise).
major=$((10#${BASH_REMATCH[1]}))
minor=$((10#${BASH_REMATCH[2]}))
patch=$((10#${BASH_REMATCH[3]}))
if [[ -n "${BASH_REMATCH[4]}" ]]; then
  rc=$((10#${BASH_REMATCH[5]}))
  (( rc >= 1 && rc <= 98 )) || { echo "rc must be 1..98: $v" >&2; exit 1; }
else
  rc=99
fi
(( minor < 100 && patch < 100 )) || { echo "MINOR and PATCH must be below 100: $v" >&2; exit 1; }
code=$(( (major * 10000 + minor * 100 + patch) * 100 + rc ))
(( code <= 2100000000 )) || { echo "version code too large: $v" >&2; exit 1; }
echo "$code"
