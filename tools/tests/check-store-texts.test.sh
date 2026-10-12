#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# tools/check-store-texts.sh on throwaway fixture trees (UT_REPO_ROOT).
set -uo pipefail
source "$(dirname "$0")/lib.sh"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# A valid tree for VERSION $1 (versionCode $2) with the release changelogs present.
fixture() {
  local root="$tmp/$3" l
  rm -rf "$root"
  for l in en-US es-ES; do
    mkdir -p "$root/fastlane/metadata/android/$l/changelogs"
    echo "UltimateTunes" > "$root/fastlane/metadata/android/$l/title.txt"
    echo "Your music" > "$root/fastlane/metadata/android/$l/short_description.txt"
    echo "Long text." > "$root/fastlane/metadata/android/$l/full_description.txt"
    echo "First pre-release." > "$root/fastlane/metadata/android/$l/changelogs/$2.txt"
    touch "$root/fastlane/metadata/android/$l/changelogs/.gitkeep"
  done
  echo "$1" > "$root/VERSION"
  echo "$root"
}
check() { UT_REPO_ROOT="$1" "$TOOLS/check-store-texts.sh" "${@:2}"; }
repeat() { python3 -c 'import sys; print(sys.argv[1] * int(sys.argv[2]), end="")' "$1" "$2"; }

r=$(fixture 0.0.1-rc.1 101 ok)
expect_out "valid tree" "" check "$r"
expect_out "valid release (0.0.1-rc.1 -> 101.txt)" "" check "$r" --release
expect_fail "unknown option" "usage" check "$r" --relase

r=$(fixture 0.0.1-rc.1 100 wrongcode)
expect_out "wrong code is fine outside a release" "" check "$r"
expect_fail "release needs <versionCode>.txt" "changelogs/101.txt" check "$r" --release

r=$(fixture 0.0.1-rc.1 101 blank)
printf ' \n\n' > "$r/fastlane/metadata/android/es-ES/changelogs/101.txt"
expect_fail "blank release changelog" "es-ES/changelogs/101.txt" check "$r" --release

r=$(fixture 1.0.0-rc.99 101 badversion)
expect_fail "invalid VERSION in a release" "rc must be 1..98" check "$r" --release

r=$(fixture 0.0.1 199 limits)
repeat a 50 > "$r/fastlane/metadata/android/en-US/title.txt"
repeat ñ 80 > "$r/fastlane/metadata/android/es-ES/short_description.txt"
repeat é 500 > "$r/fastlane/metadata/android/es-ES/changelogs/199.txt"
expect_out "limits count characters, not bytes" "" check "$r" --release
repeat a 51 > "$r/fastlane/metadata/android/en-US/title.txt"
expect_fail "title over 50" "title.txt has 51 characters (max 50)" check "$r"

r=$(fixture 0.0.1 199 short)
repeat x 81 > "$r/fastlane/metadata/android/en-US/short_description.txt"
expect_fail "short description over 80" "max 80" check "$r"

r=$(fixture 0.0.1 199 full)
repeat x 4001 > "$r/fastlane/metadata/android/es-ES/full_description.txt"
expect_fail "full description over 4000" "max 4000" check "$r"

r=$(fixture 0.0.1 199 changelog)
repeat x 501 > "$r/fastlane/metadata/android/en-US/changelogs/42.txt"
expect_fail "any changelog over 500" "42.txt has 501 characters (max 500)" check "$r"

r=$(fixture 0.0.1 199 name)
echo "x" > "$r/fastlane/metadata/android/en-US/changelogs/notes.txt"
expect_fail "changelog not named <versionCode>.txt" "notes.txt must be named" check "$r"

r=$(fixture 0.0.1 199 missing)
rm "$r/fastlane/metadata/android/es-ES/title.txt"
expect_fail "missing title" "es-ES/title.txt is missing" check "$r"

r=$(fixture 0.0.1 199 utf8)
printf '\xff\xfe' > "$r/fastlane/metadata/android/en-US/full_description.txt"
expect_fail "invalid UTF-8" "not valid UTF-8" check "$r"

# The repository's own texts pass.
expect_out "repository texts" "" "$TOOLS/check-store-texts.sh"

finish
