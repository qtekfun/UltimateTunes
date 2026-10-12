#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Takes the store and README screenshots (PLAN T23) on a connected phone: runs ScreenshotsTest
# (the app against the debug demo server: invented artists and covers only), then copies the
# pictures into fastlane/metadata/android/<locale>/images/phoneScreenshots/ and docs/images/.
# Install first, without uninstalling anything:
#   (cd android && ./gradlew installDebug installDebugAndroidTest)
# ANDROID_SERIAL picks the device. Android 13+ (per-app language and theme).
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
pkg=com.qtekfun.ultimatetunes
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

adb shell run-as "$pkg" rm -rf files/screenshots
out=$(adb shell am instrument -w -e screenshots true \
  -e class "$pkg.screenshots.ScreenshotsTest" "$pkg.test/$pkg.HiltTestRunner")
echo "$out"
grep -q '^OK (1 test)' <<<"$out" || { echo "ScreenshotsTest did not pass" >&2; exit 1; }

adb exec-out run-as "$pkg" tar -C files -cf - screenshots | tar -C "$tmp" -xf -
adb shell run-as "$pkg" rm -rf files/screenshots

for locale in en-US es-ES; do
  dest="$root/fastlane/metadata/android/$locale/images/phoneScreenshots"
  mkdir -p "$dest"
  rm -f "$dest"/*.png
  cp "$tmp/screenshots/$locale"/*.png "$dest/"
done

# A few for the README, smaller.
mkdir -p "$root/docs/images"
for shot in 01_listen_now_light 05_album_light 13_player_dark 14_lyrics_dark; do
  magick "$tmp/screenshots/en-US/$shot.png" -resize 540x -strip "$root/docs/images/${shot#*_}.png"
done
echo "Screenshots in fastlane/metadata/android/*/images/phoneScreenshots and docs/images"
