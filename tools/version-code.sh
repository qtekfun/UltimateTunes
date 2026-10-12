#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# SemVer[-rc.N] -> Android versionCode: (MAJOR*10000 + MINOR*100 + PATCH)*100 + N, N = 99 for finals.
# 1.0.0-rc.1 -> 1000001, 1.0.0 -> 1000099. Gradle implements the same formula (with a test).
set -euo pipefail
v=${1:?usage: tools/version-code.sh X.Y.Z[-rc.N]}
[[ "$v" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)(-rc\.([0-9]+))?$ ]] || { echo "bad version: $v" >&2; exit 1; }
rc=${BASH_REMATCH[5]:-99}
(( rc >= 1 && rc <= 98 || rc == 99 )) || { echo "rc must be 1..98" >&2; exit 1; }
echo $(( (BASH_REMATCH[1] * 10000 + BASH_REMATCH[2] * 100 + BASH_REMATCH[3]) * 100 + rc ))
