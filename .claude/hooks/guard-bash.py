#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""PreToolUse(Bash): blocks commands that break the rules in CLAUDE.md.

Exit code 2 blocks the tool call and shows stderr to Claude.
"""
import json
import os
import re
import shlex
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
# Git commands are also checked token by token, segment by segment (`;`, `&&`, `||`, `|`, new
# lines), after the global options (`git -C dir`, `-c k=v`, `--git-dir=…`), so quoting, chaining
# or `git -C` cannot get around the rules above.
# Release tags: the author allowed Claude to create and push them (2026-10-13), but only the tag
# of the version on master (`v` + VERSION), from master, never deleted, moved or forced, and
# never several refs at once.
_GLOBAL_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env"}
_VERSION_TAG = re.compile(r"^v\d+\.\d+\.\d+")
_MASTER = {"master", "refs/heads/master"}


def _segments(text: str) -> list[list[str]]:
    out = []
    for seg in re.split(r"&&|\|\||[;|\n]", text):
        try:
            out.append(shlex.split(seg))
        except ValueError:
            out.append(seg.split())
    return out


def _git_call(tokens: list[str]) -> tuple[str, str, list[str]] | None:
    """(directory, subcommand, arguments) of a git call, or None."""
    i = 0
    while i < len(tokens) and re.match(r"^[A-Za-z_]\w*=", tokens[i]):
        i += 1
    if i >= len(tokens) or os.path.basename(tokens[i]) != "git":
        return None
    i += 1
    directory = workdir
    while i < len(tokens) and tokens[i].startswith("-"):
        opt = tokens[i]
        if opt in _GLOBAL_WITH_VALUE and i + 1 < len(tokens):
            if opt == "-C":
                directory = os.path.join(directory, os.path.expanduser(tokens[i + 1]))
            i += 2
        else:
            i += 1
    if i >= len(tokens):
        return None
    return directory, tokens[i], tokens[i + 1 :]


def _version_of(directory: str) -> str:
    try:
        with open(os.path.join(directory, "VERSION"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _branch_of(directory: str) -> str:
    try:
        return subprocess.run(
            ["git", "-C", directory, "branch", "--show-current"], capture_output=True, text=True, check=False
        ).stdout.strip()
    except OSError:
        return ""


def _short_flags(arg: str) -> str:
    """The flags of a short-option group, up to one that takes the rest as its value (`-mfix`)."""
    if not re.match(r"^-[A-Za-z]+$", arg):
        return ""
    return re.split(r"[mF]", arg[1:], maxsplit=1)[0]


def _check_tags(directory: str, tags: list[str]) -> None:
    if not tags:
        return
    version = _version_of(directory)
    for name in tags:
        if name != f"v{version}":
            block(f"only the tag of the current VERSION (v{version or '?'}) may be created or pushed.")
    if _branch_of(directory) != "master":
        block("release tags are created from an up-to-date master (RELEASING.md).")


def _check_push(directory: str, args: list[str]) -> None:
    positional = []
    for arg in args:
        flags = _short_flags(arg)
        if arg in ("--force", "--force-with-lease", "--force-if-includes") or arg.startswith("--force-with-lease=") or "f" in flags:
            block("no force-push (CLAUDE.md, Workflow).")
        if arg in ("--delete", "--prune", "--mirror", "--all", "--tags", "--follow-tags") or "d" in flags:
            block("push one ref at a time; never delete, prune or mirror (RELEASING.md).")
        if not arg.startswith("-"):
            positional.append(arg)
    tags = []
    for spec in positional[1:]:  # the first one is the remote
        if spec.startswith("+") or spec.startswith(":") or "*" in spec:
            block("no forced, deleting or wildcard refspecs.")
        src, _, dst = spec.partition(":")
        dst = dst or src
        if dst in _MASTER or dst.endswith("/master") and dst.startswith("refs/heads/"):
            if remote_has_master():
                block("never push to master; open a PR from your branch.")
        names = [s.removeprefix("refs/tags/") for s in (src, dst)]
        if any(_VERSION_TAG.match(n) for n in names):
            if names[0] != names[1]:
                block("a release tag is pushed under its own name.")
            tags.append(names[0])
    _check_tags(directory, tags)


def _check_tag(directory: str, args: list[str]) -> None:
    names = []
    skip = False
    for arg in args:
        if skip:
            skip = False
            continue
        flags = _short_flags(arg)
        if arg in ("-m", "-F", "-u", "--message", "--file", "--local-user", "--cleanup", "--format", "--sort", "--contains", "--no-contains", "--points-at", "--merged", "--no-merged"):
            skip = True
            continue
        if arg in ("--delete", "--force") or "d" in flags or "f" in flags:
            if any(_VERSION_TAG.match(a) for a in args):
                block("release tags are never deleted, moved or forced (RELEASING.md); ask the author.")
        if _VERSION_TAG.match(arg):
            names.append(arg)
        elif names and not arg.startswith("-"):
            block("a release tag goes on the checked-out master HEAD; do not name another commit.")
    _check_tags(directory, names)


for _tokens in _segments(cmd):
    _call = _git_call(_tokens)
    if _call is None:
        continue
    _dir, _sub, _args = _call
    if _sub == "push":
        _check_push(_dir, _args)
    elif _sub == "tag":
        _check_tag(_dir, _args)

# Second, conservative layer on the raw text, so shell constructs the token parser does not model
# (subshells, `bash -c`, `$(…)`, `xargs`, quoted separators, `cd` in the middle) cannot reach a
# release tag. Any command that names a version tag must name only the current one, from master,
# with nothing around it that could delete, move, force or re-route it.
_RAW_TAG = re.compile(r"(?<![\w.-])v\d+\.\d+\.\d+[\w.+-]*")
_RAW_DANGER = re.compile(
    r"--delete\b|(?<!\S)-[a-ln-zA-EG-Z]*[df]|--force|--mirror|--prune\b|--tags\b|--follow-tags"
    r"|(?<![\w/-])[+:]\s*['\"]*\s*(refs/tags/|tags/)?v\d|['\"]{2}\s*:|\bxargs\b|\beval\b|\b(ba|z|da)?sh\s+-c\b"
    r"|\$\(|`|\bgit\s+config\b|\s-c\s+\S|--config-env|(?:^|[;&|(\n]\s*)cd\s|\bpushd\b"
)
_DELETE_OR_FORCE = re.compile(
    r"--delete\b|(?<!\S)-[a-ln-zA-EG-Z]*[df][a-ln-zA-EG-Z]*(?!\S)|--force|--mirror|--prune\b"
)
if re.search(r"\bgit\b", cmd):
    # A computed name (`v$(cat VERSION)`, `v$V`, `` v`…` ``) would skip every check below.
    if re.search(r"\b(push|tag)\b", cmd) and re.search(r"(?<![\w.-])['\"]?v['\"]?(\$|`)", cmd):
        block("spell the release tag out (v1.2.3), never compute it in the command (RELEASING.md).")
    # Deleting or forcing something whose name is computed could hit a release tag.
    if re.search(r"[$`]", cmd) and _DELETE_OR_FORCE.search(cmd) and re.search(r"\b(push|tag)\b", cmd):
        block("no delete or force on a computed ref name; spell it out (RELEASING.md).")
    _named = {m.group(0) for m in _RAW_TAG.finditer(cmd)}
    if _named and re.search(r"\b(push|tag|update-ref)\b|refs/tags/", cmd):
        _lead = re.match(r"\s*cd\s+(\S+)\s*&&", cmd)
        _rest = cmd[_lead.end():] if _lead else cmd
        _version = _version_of(workdir)
        if _named != {f"v{_version}"}:
            block(f"a command that names a release tag may name only v{_version or '?'} (RELEASING.md).")
        if _RAW_DANGER.search(_rest):
            block("release tag commands stay plain: no delete, force, wildcard, config, wrapper or cd "
                  "in the middle (RELEASING.md); tag and push in separate simple commands.")
        if _branch_of(workdir) != "master":
            block("release tags are created from an up-to-date master (RELEASING.md).")
# Push behaviour must not be changed through config or aliases.
if re.search(r"\bgit\b.*(\s-c\s+|--config-env[=\s]|\bconfig\s+(--\S+\s+)*)(push\.|remote\.[^.\s]+\.(push|mirror)|alias\.)", cmd, re.I):
    block("do not change push behaviour or define aliases through git config.")
if re.search(r"\bcurl\b.*\|\s*(ba|z)?sh\b", cmd):
    block("do not pipe downloads into a shell.")
sys.exit(0)
