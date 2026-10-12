#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Checks the fastlane store texts (F-Droid limits: title 50, short description 80, full
# description 4000, changelog 500 characters; changelogs named <versionCode>.txt). With
# --release, also requires non-empty en-US and es-ES changelogs for the versionCode of VERSION,
# which the release PR (branch release/*) has already bumped. See RELEASING.md.
# UT_REPO_ROOT overrides the repository root (tests, tools/tests/).
set -euo pipefail

tools=$(cd "$(dirname "$0")" && pwd)
cd "${UT_REPO_ROOT:-$tools/..}"
meta=fastlane/metadata/android
locales=(en-US es-ES)
fail=0

case "${1:-}" in
  "" | --release) ;;
  *) echo "usage: tools/check-store-texts.sh [--release]" >&2; exit 2 ;;
esac

err() { echo "::error::$*"; fail=1; }

chars() { # file -> number of characters (not bytes), without the trailing newlines
  python3 -c 'import sys; print(len(open(sys.argv[1], encoding="utf-8").read().rstrip("\n")))' "$1"
}

max_chars() { # file limit [required]
  if [[ ! -f "$1" ]]; then
    [[ -z "${3:-}" ]] || err "$1 is missing"
    return 0
  fi
  local n
  n=$(chars "$1") || { err "$1 is not valid UTF-8"; return 0; }
  (( n <= $2 )) || err "$1 has $n characters (max $2)"
}

for l in "${locales[@]}"; do
  max_chars "$meta/$l/title.txt" 50 required
  max_chars "$meta/$l/short_description.txt" 80 required
  max_chars "$meta/$l/full_description.txt" 4000 required
  for f in "$meta/$l"/changelogs/*; do
    [[ -e "$f" ]] || continue
    case "$(basename "$f")" in
      .gitkeep) ;;
      [1-9]*.txt) [[ "$(basename "$f" .txt)" =~ ^[1-9][0-9]*$ ]] || err "$f must be named <versionCode>.txt"
                  max_chars "$f" 500 ;;
      *) err "$f must be named <versionCode>.txt" ;;
    esac
  done
done

if [[ "${1:-}" == "--release" ]]; then
  version=$(tr -d '[:space:]' < VERSION)
  code=$("$tools/version-code.sh" "$version")
  for l in "${locales[@]}"; do
    f="$meta/$l/changelogs/$code.txt"
    [[ -f "$f" && -n "$(tr -d '[:space:]' < "$f")" ]] \
      || err "Release $version needs $f (≤ 500 characters, user-facing summary)"
  done
fi

exit $fail
