#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# tools/release-notes.sh extracts exactly one version's section of CHANGELOG.md.
set -uo pipefail
source "$(dirname "$0")/lib.sh"
rn="$TOOLS/release-notes.sh"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

cat > "$tmp/CHANGELOG.md" <<'MD'
# Changelog

## [Unreleased]

- Not yet.

## [0.0.1-rc.10] - 2026-10-20

- Tenth candidate.

## [0.0.1] - 2026-10-14

### Fixed
- Final fix.

## [0.0.1-rc.1] - 2026-10-12

### Added
- First pre-release.


## [1a2a3] - 2026-01-01

- Dots must not match any character.

## [0.0.0] - 2026-01-01

MD

expect_out "rc section, blank lines trimmed" $'### Added\n- First pre-release.' "$rn" 0.0.1-rc.1 "$tmp/CHANGELOG.md"
expect_out "final is not its candidates" $'### Fixed\n- Final fix.' "$rn" 0.0.1 "$tmp/CHANGELOG.md"
expect_out "rc.10 is not rc.1" "- Tenth candidate." "$rn" 0.0.1-rc.10 "$tmp/CHANGELOG.md"
expect_fail "missing version" "no notes for [0.0.2]" "$rn" 0.0.2 "$tmp/CHANGELOG.md"
expect_fail "empty section" "no notes for [0.0.0]" "$rn" 0.0.0 "$tmp/CHANGELOG.md"
expect_fail "dots are literal" "no notes for [1.2.3]" "$rn" 1.2.3 "$tmp/CHANGELOG.md"
expect_fail "no argument" "usage" "$rn"

finish
