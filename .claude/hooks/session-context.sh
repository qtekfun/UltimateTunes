#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# SessionStart: tells Claude where it is (worktree, branch, task, next open PLAN task). Stdout becomes context.
cd "$CLAUDE_PROJECT_DIR" || exit 0
branch=$(git branch --show-current 2>/dev/null)
next=$(grep -m1 -E '^- \[ \] \*\*T[0-9]+[a-z]?' PLAN.md 2>/dev/null | sed -E 's/^- \[ \] \*\*([^*]+)\*\*.*/\1/')
echo "Worktree: $(pwd). Branch: ${branch:-unknown}. Next open PLAN task: ${next:-none}."
if [[ "$branch" =~ ^feat/(t[0-9]+[a-z]?)- ]]; then
  echo "You are implementing PLAN ${BASH_REMATCH[1]^^}: only the paths of that task in .claude/ownership.json are writable."
fi
if [[ "$branch" == "master" ]]; then
  echo "You are on master: create a branch (tools/worktree.sh <task>) before changing anything."
fi
