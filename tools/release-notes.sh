#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Prints the notes of one version from CHANGELOG.md: the lines under `## [X.Y.Z] - YYYY-MM-DD`
# up to the next `## [` heading, without leading and trailing blank lines. Fails when the
# section is missing or empty. Used by the Release workflow; tested by tools/tests/.
#   tools/release-notes.sh X.Y.Z[-rc.N] [CHANGELOG.md]
set -euo pipefail
version=${1:?usage: tools/release-notes.sh X.Y.Z[-rc.N] [CHANGELOG.md]}
changelog=${2:-"$(dirname "$0")/../CHANGELOG.md"}

# Literal comparison (index), so the dots of the version are not regex wildcards.
notes=$(awk -v head="## [$version]" '
  index($0, head) == 1 && (length($0) == length(head) || substr($0, length(head) + 1, 1) == " ") { found = 1; next }
  found && /^## \[/ { exit }
  found { print }
' "$changelog" | sed -e '/./,$!d' | sed -e ':a' -e '/^\n*$/{$d;N;ba' -e '}')

[[ -n "${notes//[[:space:]]/}" ]] || { echo "CHANGELOG has no notes for [$version]: add '## [$version] - YYYY-MM-DD' with its notes" >&2; exit 1; }
printf '%s\n' "$notes"
