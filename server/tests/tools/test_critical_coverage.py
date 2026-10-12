# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The 100 % gate of the critical modules (tools/critical_coverage.py)."""

from fnmatch import fnmatchcase
from pathlib import Path

import pytest

from critical_coverage import CRITICAL, check, main, parse_report

REPORT = """<?xml version="1.0" ?>
<coverage version="7.0">
  <packages><package name="p"><classes>
    <class name="keys.py" filename="src/ultimatetunes/auth/keys.py">
      <lines>
        <line number="1" hits="1"/>
        <line number="2" hits="1" branch="true" condition-coverage="100% (2/2)"/>
      </lines>
    </class>
    <class name="sanitize.py" filename="src/ultimatetunes/paths/sanitize.py">
      <lines>
        <line number="1" hits="1"/>
        <line number="2" hits="1" branch="true" condition-coverage="50% (1/2)"/>
        <line number="3" hits="0"/>
      </lines>
    </class>
    <class name="app.py" filename="src/ultimatetunes/app.py">
      <lines><line number="1" hits="0"/></lines>
    </class>
  </classes></package></packages>
</coverage>
"""
COMPLETE = REPORT.replace('hits="0"', 'hits="1"').replace("50% (1/2)", "100% (2/2)")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A server/ tree with the files the report names."""
    for name in ("auth/keys.py", "paths/sanitize.py", "app.py"):
        path = tmp_path / "src/ultimatetunes" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x = 1\n")
    return tmp_path


def write(root: Path, name: str, text: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_parse_report_finds_missed_lines_and_partial_branches(root: Path) -> None:
    files = {f.name: f for f in parse_report(write(root, "c.xml", REPORT))}
    assert files["src/ultimatetunes/auth/keys.py"].complete
    sanitize = files["src/ultimatetunes/paths/sanitize.py"]
    assert sanitize.missed_lines == (3,)
    assert sanitize.partial_branches == (2,)


def test_incomplete_critical_file_fails_and_others_are_ignored(root: Path) -> None:
    failures, notes = check(parse_report(write(root, "c.xml", REPORT)), CRITICAL, root)
    assert len(failures) == 1
    assert "src/ultimatetunes/paths/sanitize.py" in failures[0]
    assert "[3]" in failures[0]
    # app.py is below 100 % but not critical; areas with no code yet are only noted.
    assert not any("app.py" in f for f in failures)
    assert any("ids/*" in note and "yet" in note for note in notes)


def test_a_critical_file_missing_from_the_report_fails(root: Path) -> None:
    write(root, "src/ultimatetunes/ids/resolve.py", "x = 1\n")
    failures, _ = check(parse_report(write(root, "c.xml", COMPLETE)), CRITICAL, root)
    assert failures == [
        "src/ultimatetunes/ids/resolve.py (id resolution (yt: <-> library)): "
        "not in the coverage report (never measured)"
    ]


def test_a_report_with_other_file_names_fails(root: Path) -> None:
    drifted = COMPLETE.replace('filename="src/ultimatetunes/', 'filename="ultimatetunes/')
    failures, _ = check(parse_report(write(root, "c.xml", drifted)), CRITICAL, root)
    assert any("report layout changed" in f for f in failures)


@pytest.mark.parametrize(
    "line",
    ["x = 1  # pragma: no cover", "if x:  # pragma: no branch", "y = 2  #pragma:NO COVER"],
)
def test_exclusion_pragmas_in_critical_files_fail(root: Path, line: str) -> None:
    write(root, "src/ultimatetunes/auth/keys.py", f"a = 0\n{line}\n")
    failures, _ = check(parse_report(write(root, "c.xml", COMPLETE)), CRITICAL, root)
    assert len(failures) == 1
    assert "src/ultimatetunes/auth/keys.py" in failures[0]
    assert "pragma on lines [2]" in failures[0]


def test_exclusion_pragmas_outside_critical_files_are_not_this_gates_business(
    root: Path,
) -> None:
    write(root, "src/ultimatetunes/app.py", "x = 1  # pragma: no cover\n")
    failures, _ = check(parse_report(write(root, "c.xml", COMPLETE)), CRITICAL, root)
    assert failures == []


@pytest.mark.parametrize(
    "name",
    [
        "src/ultimatetunes/auth/passwords.py",
        "src/ultimatetunes/core/ratelimit.py",
        "src/ultimatetunes/auth/rate_limiter.py",
        "src/ultimatetunes/ids/resolve.py",
        "src/ultimatetunes/paths/sanitizer.py",
        "src/ultimatetunes/jobs/state.py",
        "src/ultimatetunes/streaming/state_machine.py",
    ],
)
def test_every_critical_area_has_a_pattern(name: str) -> None:
    assert any(fnmatchcase(name, pattern) for pattern in CRITICAL.values())


def test_main_exit_codes(root: Path) -> None:
    assert main(["x", str(write(root, "c.xml", REPORT)), str(root)]) == 1
    assert main(["x", str(root / "missing.xml"), str(root)]) == 2
    assert main(["x", str(write(root, "ok.xml", COMPLETE)), str(root)]) == 0
