#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# .claude/hooks/guard-bash.py: the release-tag and push rules (RELEASING.md, CLAUDE.md). Runs the
# hook on throwaway repositories (no remote, no network): one on `master` with VERSION 1.0.0-rc.2,
# one on a feature branch.
set -uo pipefail
source "$(dirname "$0")/lib.sh"
hook="$TOOLS/../.claude/hooks/guard-bash.py"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

for repo in main branch; do
  git init -q -b master "$tmp/$repo"
  echo 1.0.0-rc.2 > "$tmp/$repo/VERSION"
  git -C "$tmp/$repo" -c user.name=t -c user.email=t@example.com add VERSION
  git -C "$tmp/$repo" -c user.name=t -c user.email=t@example.com commit -qm init
done
git -C "$tmp/branch" switch -q -c feat/x

# hook_exit DIR COMMAND: the hook's exit code (0 allowed, 2 blocked).
hook_exit() {
  python3 -c 'import json, sys; print(json.dumps({"cwd": sys.argv[1], "tool_input": {"command": sys.argv[2]}}))' "$1" "$2" |
    "$hook" >/dev/null 2>&1
  echo $?
}
allowed() { expect_out "allowed: $2" 0 hook_exit "$1" "$2"; }
blocked() { expect_out "blocked: $2" 2 hook_exit "$1" "$2"; }

m="$tmp/main" b="$tmp/branch" t=v1.0.0-rc.2 push="git push" tag="git tag"

# The tag of the current VERSION, from master.
allowed "$m" "$tag -a $t -m \"UltimateTunes 1.0.0-rc.2\""
allowed "$m" "$tag -a -m \"UltimateTunes v1.0.0-rc.2\" $t"
allowed "$m" "$tag -s $t -m x"
allowed "$m" "$push origin $t"
allowed "$m" "$push origin refs/tags/$t"
allowed "$m" "$tag -a $t -m x&&$push origin $t"
allowed "$m" "git -C $m push origin $t"
allowed "$m" "$tag -l && echo v0.9.0"
allowed "$m" "$push -u origin feat/x"
allowed "$m" "git status"

# Other versions, or not from master.
blocked "$m" "$tag -a v1.0.0-rc.3 -m x"
blocked "$m" "$push origin v1.0.0-rc.1"
blocked "$m" "git -c x=y push origin v9.9.9"
blocked "$m" "git -C $m push origin v9.9.9"
blocked "$m" "$push origin HEAD:refs/tags/$t"
blocked "$b" "$tag $t"
blocked "$m" "git -C $b tag $t"

# Never deleted, moved or forced; flags before or after the name.
blocked "$m" "$tag -d $t"
blocked "$m" "$tag $t -d"
blocked "$m" "$tag -a $t -f -m x"
blocked "$m" "$tag -a $t --force -m x"
blocked "$m" "$tag -af $t -m x"
blocked "$m" "git -C $m tag -d $t"
blocked "$m" "$push origin --delete $t"
blocked "$m" "$push origin $t --delete"
blocked "$m" "$push origin $t -d"
blocked "$m" "$push origin :$t"
blocked "$m" "$push origin :refs/tags/$t"
blocked "$m" "$push origin '':refs/tags/$t"
blocked "$m" "$push origin +$t"
blocked "$m" "$push origin \"+\"$t"
blocked "$m" "$push --force origin $t"
blocked "$m" "$push origin $t --force"

# One ref at a time; every command of a chain is checked.
blocked "$m" "$push --tags"
blocked "$m" "$push --follow-tags origin"
blocked "$m" "$push --mirror"
blocked "$m" "$push origin 'refs/tags/*'"
blocked "$m" "$push origin $t && $push origin :v1.0.0-rc.1"
blocked "$m" "$push origin $t; $push origin --delete v1.0.0-rc.1"
blocked "$m" "$tag -a $t -m x && $tag -d v1.0.0-rc.1"

# master and releases stay out of reach.
blocked "$m" "$push origin master"
blocked "$m" "$push origin HEAD:master"
blocked "$m" "git -C $m push --force origin master"
blocked "$m" "gh release create $t"

finish
