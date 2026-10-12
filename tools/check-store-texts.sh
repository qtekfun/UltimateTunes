#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Checks the fastlane store texts (F-Droid limits). With --release, also requires the
# en-US and es-ES changelogs for the versionCode of VERSION, which the release PR
# (branch release/*) has already bumped. See RELEASING.md.
set -euo pipefail

cd "$(dirname "$0")/.."
meta=fastlane/metadata/android
locales=(en-US es-ES)
fail=0

err() { echo "::error::$*"; fail=1; }

max_chars() { # file limit
  [[ -f "$1" ]] || return 0
  local n
  n=$(python3 -c 'import sys; print(len(open(sys.argv[1], encoding="utf-8").read().rstrip("\n")))' "$1")
  (( n <= $2 )) || err "$1 has $n characters (max $2)"
}

for l in "${locales[@]}"; do
  max_chars "$meta/$l/title.txt" 50
  max_chars "$meta/$l/short_description.txt" 80
  max_chars "$meta/$l/full_description.txt" 4000
  for f in "$meta/$l"/changelogs/*.txt; do
    [[ -e "$f" ]] && max_chars "$f" 500
  done
done

if [[ "${1:-}" == "--release" ]]; then
  version=$(tr -d '[:space:]' < VERSION)
  code=$(tools/version-code.sh "$version")
  for l in "${locales[@]}"; do
    f="$meta/$l/changelogs/$code.txt"
    [[ -s "$f" ]] || err "Release $version needs $f (≤ 500 characters, user-facing summary)"
  done
fi

exit $fail
