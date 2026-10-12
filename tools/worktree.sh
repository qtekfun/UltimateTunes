#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Creates the git worktree and branch for a PLAN task, next to the main checkout:
#   tools/worktree.sh t06 search      -> ../ut-t06, branch feat/t06-search, from origin/master
# Prints the path. Used by the coordinator before launching a stream subagent.
set -euo pipefail
cd "$(dirname "$0")/.."
task=${1:?usage: tools/worktree.sh <tNN> <slug>}
slug=${2:?usage: tools/worktree.sh <tNN> <slug>}
[[ "$task" =~ ^t[0-9]{2}[a-z]?$ ]] || { echo "task must look like t06 or t03a" >&2; exit 1; }
[[ "$slug" =~ ^[a-z0-9-]+$ ]] || { echo "slug: lowercase letters, digits and dashes" >&2; exit 1; }
git fetch -q origin master
path="../ut-$task"
git worktree add -b "feat/$task-$slug" "$path" origin/master >/dev/null
echo "$(cd "$path" && pwd)"
