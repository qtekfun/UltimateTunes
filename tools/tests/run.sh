#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Runs every tools/tests/*.test.sh (plain bash; no test framework is an approved dependency).
set -uo pipefail
status=0
for t in "$(dirname "$0")"/*.test.sh; do
  bash "$t" || status=1
done
exit $status
