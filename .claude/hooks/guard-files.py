#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""PreToolUse(Edit|Write): protects generated files, release files, quality gates and stream ownership.

- deny: generated/lock files, release files outside release/*, paths outside the task's ownership.
- ask:  quality gates, CI and Claude config; the user approves, never to make CI pass.
"""
import fnmatch
import json
import os
import re
import subprocess
import sys

data = json.load(sys.stdin)
tool_input = data.get("tool_input", {})
path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
if not path:
    sys.exit(0)
path = os.path.abspath(path)


def toplevel(p: str) -> str:
    """Repository (or worktree) that contains p; subagents edit inside their own worktree."""
    d = p if os.path.isdir(p) else os.path.dirname(p)
    while d and not os.path.isdir(d):
        d = os.path.dirname(d)
    try:
        out = subprocess.run(["git", "-C", d, "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, check=False).stdout.strip()
    except OSError:
        out = ""
    return out or os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())


root = toplevel(path)
rel = os.path.relpath(path, root)


def decide(decision: str, reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
        "permissionDecisionReason": reason,
    }}))
    sys.exit(0)


def branch() -> str:
    try:
        return subprocess.run(["git", "-C", root, "branch", "--show-current"],
                              capture_output=True, text=True, check=False).stdout.strip()
    except OSError:
        return ""


if not rel or rel.startswith(".."):
    sys.exit(0)
b = branch()
new_text = json.dumps(tool_input)

DENY = {
    "server/uv.lock": "regenerate it with `uv lock`, never by hand.",
    "android/gradle/verification-metadata.xml": "regenerate it with --write-verification-metadata, never by hand.",
}
if rel in DENY:
    decide("deny", DENY[rel])
if rel in ("VERSION", "CHANGELOG.md") and not b.startswith("release/"):
    decide("deny", f"{rel} changes only in a release PR (branch release/X.Y.Z, RELEASING.md).")
if re.search(r"(^|/)\.env$|\.jks$|\.keystore$|(^|/)secrets?/", rel):
    decide("deny", "secrets never live in the repository.")

# Stream ownership on feat/tNN-* branches.
m = re.match(r"^feat/(t\d+[a-z]?)-", b)
if m:
    try:
        with open(os.path.join(root, ".claude", "ownership.json"), encoding="utf-8") as f:
            own = json.load(f)
    except (OSError, ValueError):
        own = {}
    globs = own.get("tasks", {}).get(m.group(1))
    if globs is not None:
        allowed = globs + own.get("always", [])
        if not any(fnmatch.fnmatch(rel, g) for g in allowed):
            decide("deny", f"{rel} is outside the paths of {m.group(1).upper()} (.claude/ownership.json). "
                           "If you need it, stop and ask the coordinator in your PR description.")

if rel.startswith("contracts/") and not re.match(r"^(contracts/|feat/t0[0-2]-)", b) \
        and not re.match(r"^contracts/db/migrations/\d{4}_", rel):
    decide("ask", "contracts/ is frozen during a wave; only the coordinator changes it, on a contracts/* branch.")
if rel == "server/pyproject.toml" and re.search(r"dependencies|fail_under|fail-under|\[tool\.(ruff|mypy|bandit)", new_text):
    decide("ask", "pyproject.toml: dependencies and quality settings need the user's approval "
                  "(license check for new dependencies; gates are never relaxed).")
if rel == "android/gradle/libs.versions.toml" and re.search(r'=\s*\\?"\d', new_text):
    decide("ask", "Changing a version or adding a dependency: Dependabot bumps versions, "
                  "and new dependencies need a license check and the user's approval.")
for pattern in (r"^android/config/detekt/", r"^\.github/", r"^\.claude/", r"^android/(app/|core/\w+/)?build\.gradle\.kts$",
                r"^server/Dockerfile$", r"^server/compose(\.test)?\.ya?ml$", r"^\.gitleaks\.toml$"):
    if re.search(pattern, rel):
        decide("ask", f"{rel} is a quality/CI/build file: only change it for the task at hand, never to relax a gate.")
sys.exit(0)
