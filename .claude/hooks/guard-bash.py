#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""PreToolUse(Bash): blocks commands that break the rules in CLAUDE.md.

Exit code 2 blocks the tool call and shows stderr to Claude.
"""
import json
import os
import re
import subprocess
import sys

data = json.load(sys.stdin)
cmd = data.get("tool_input", {}).get("command", "")
# Subagents work in git worktrees: resolve the directory the command really runs in.
m = re.match(r"\s*cd\s+(\S+)\s*&&", cmd) or re.search(r"\bgit\s+-C\s+(\S+)", cmd)
workdir = os.path.join(data.get("cwd") or os.getcwd(), os.path.expanduser(m.group(1))) if m else (data.get("cwd") or os.getcwd())


def block(reason: str) -> None:
    print(f"Blocked by .claude/hooks/guard-bash.py: {reason}", file=sys.stderr)
    sys.exit(2)


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", workdir, *args], capture_output=True, text=True, check=False)


def branch() -> str:
    try:
        return git("branch", "--show-current").stdout.strip()
    except OSError:
        return ""


def has_commits() -> bool:
    try:
        return git("rev-parse", "--verify", "-q", "HEAD").returncode == 0
    except OSError:
        return True


if re.search(r"\bgit\s+push\b.*(\s--force(-with-lease)?\b|\s-f\b|\s\+\S)", cmd):
    block("no force-push (CLAUDE.md, Workflow).")
def remote_has_master() -> bool:
    try:
        r = git("ls-remote", "--heads", "origin", "master")
        return r.returncode != 0 or bool(r.stdout.strip())
    except OSError:
        return True


# Only the first push of master (an empty remote, right after `gh repo create`) is allowed.
if re.search(r"\bgit\s+push\b.*\b(origin\s+)?(HEAD:)?master\b", cmd) and remote_has_master():
    block("never push to master; open a PR from your branch.")
# The very first commit (the spec pack) is the only one allowed on master.
if re.search(r"\bgit\s+commit\b", cmd) and branch() == "master" and has_commits():
    block("you are on master; create a branch first (tools/worktree.sh <task>).")
if re.search(r"--no-verify\b", cmd):
    block("do not skip git hooks.")
if re.search(r"\bgit\s+(rebase\s+-i|reset\s+--hard\s+origin|filter-branch|filter-repo)", cmd):
    block("no history rewriting.")
if re.search(r"\bgradlew\b.*\s-x\s+\S*(check|test|detekt|ktlint|lint|kover)", cmd, re.I):
    block("do not exclude quality tasks; `./gradlew check` must pass as is.")
if re.search(r"\bgradlew\b.*\bconnected\w*AndroidTest\b", cmd):
    block("connected*AndroidTest uninstalls the app and wipes its data on the author's phone; "
          "use installDebug installDebugAndroidTest + adb shell am instrument (CLAUDE.md, Commands). "
          "CI runs it on an emulator.")
if re.search(r"\bpytest\b.*(--no-cov|--cov-fail-under[= ]?0\b|-p\s+no:cov)", cmd):
    block("do not turn coverage off; the thresholds in pyproject.toml are part of the gate.")
if re.search(r"\b(ruff|mypy|bandit)\b.*(--exit-zero|--ignore-missing-imports\s*$)", cmd):
    block("do not silence the linters; fix the findings.")
if re.search(r"\bpip\s+install\b", cmd) and not re.search(r"\buv\s+pip\b", cmd):
    block("dependencies go through uv and pyproject.toml (and need the user's approval if new).")
if re.search(r"\b(uv\s+add|npm\s+i(nstall)?\s+\S|cargo\s+add)\b", cmd):
    block("adding a dependency needs a license check and the user's approval first (CLAUDE.md).")
if re.search(r"(^|[;&|(]\s*|\b(uv\s+run|uvx|python3?\s+-m)\s+)(\S*/)?yt[-_]dlp\s(?!.*(--simulate|--version|--help|-U\b))", cmd):
    block("no real downloads from the shell; tests use the fake downloader (CLAUDE.md). "
          "Spikes T03* may ask the user for an exception.")
if re.search(r"\bgh\s+api\b.*rulesets", cmd):
    block("the user manages rulesets.")
if re.search(r"\bgh\s+release\b", cmd):
    block("releases are created by the Release workflow from a tag (RELEASING.md).")
# Release tags: the author allowed Claude to create and push them (2026-10-13), but only the tag
# of the version on master (`v` + VERSION), from master, never moved or deleted.
_tag = re.search(r"\bgit\s+tag\b(.*?)\bv(\d+\.\d+\.\d+\S*)", cmd)
_push = re.search(r"\bgit\s+push\b(.*?)\bv(\d+\.\d+\.\d+[^\s;&|]*)", cmd)
if _tag or _push:
    if (_tag and re.search(r"\s-[a-zA-Z]*[dfm]|--delete|--force", _tag.group(1))) or (
        _push and re.search(r"--delete|\s-d\b|:\s*$|\s:", _push.group(1) + " ")
    ):
        block("release tags are never deleted, moved or forced (RELEASING.md); ask the author.")
    try:
        with open(os.path.join(workdir, "VERSION"), encoding="utf-8") as f:
            version = f.read().strip()
    except OSError:
        version = ""
    for found in (_tag, _push):
        if found and found.group(2) != version:
            block(f"only the tag of the current VERSION (v{version or '?'}) may be created or pushed.")
    if branch() != "master":
        block("release tags are created from an up-to-date master (RELEASING.md).")
if re.search(r"\bcurl\b.*\|\s*(ba|z)?sh\b", cmd):
    block("do not pipe downloads into a shell.")
sys.exit(0)
