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


@pytest.fixture
def report(tmp_path: Path) -> Path:
    path = tmp_path / "coverage.xml"
    path.write_text(REPORT)
    return path


def test_parse_report_finds_missed_lines_and_partial_branches(report: Path) -> None:
    files = {f.name: f for f in parse_report(report)}
    assert files["src/ultimatetunes/auth/keys.py"].complete
    sanitize = files["src/ultimatetunes/paths/sanitize.py"]
    assert sanitize.missed_lines == (3,)
    assert sanitize.partial_branches == (2,)


def test_incomplete_critical_file_fails_and_others_are_ignored(report: Path) -> None:
    failures, notes = check(parse_report(report), CRITICAL)
    assert len(failures) == 1
    assert "src/ultimatetunes/paths/sanitize.py" in failures[0]
    assert "[3]" in failures[0]
    # app.py is below 100 % but not critical; areas with no code yet are only noted.
    assert not any("app.py" in f for f in failures)
    assert any("ids/*" in note and "yet" in note for note in notes)


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


def test_main_exit_codes(report: Path, tmp_path: Path) -> None:
    assert main(["x", str(report)]) == 1
    assert main(["x", str(tmp_path / "missing.xml")]) == 2
    complete = tmp_path / "complete.xml"
    complete.write_text(REPORT.replace('hits="0"', 'hits="1"').replace("50% (1/2)", "100% (2/2)"))
    assert main(["x", str(complete)]) == 0
