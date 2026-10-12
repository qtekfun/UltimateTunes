# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fails unless every critical module has 100 % line and branch coverage (CLAUDE.md, Quality).

The critical files are found on disk (src/ultimatetunes), so a file missing from the Cobertura
report pytest-cov writes (reports/coverage.xml) fails too, instead of passing unnoticed. The
critical areas are listed before their code exists: a pattern that matches no file yet is
reported and skipped, and it is enforced from the moment its first file appears. Coverage
exclusion pragmas are refused in critical files: they must be covered, not excluded.
"""

import re
import sys

# Our own coverage report, written by pytest-cov in this run: not untrusted input.
import xml.etree.ElementTree as ET  # nosec B405
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path

PACKAGE = "src/ultimatetunes"

# fnmatch patterns over paths relative to server/; "*" also matches "/". Only .py files count.
CRITICAL = {
    "auth (API keys, passwords, OpenSubsonic auth rules)": f"{PACKAGE}/auth/*",
    "rate limiter": f"{PACKAGE}/*rate*limit*",
    "id resolution (yt: <-> library)": f"{PACKAGE}/ids/*",
    "path sanitizer": f"{PACKAGE}/paths/*",
    "job state machine": f"{PACKAGE}/jobs/state*",
    "streaming-while-downloading state machine": f"{PACKAGE}/streaming/state*",
}

_CONDITIONS = re.compile(r"\((\d+)/(\d+)\)")
# coverage.py's default exclusion pragmas ("no cover", "no branch"), in any spacing or case.
_PRAGMA = re.compile(r"#\s*pragma:?\s*no\s*(?:cover|branch)", re.IGNORECASE)


@dataclass(frozen=True)
class FileCoverage:
    """Missed lines and partially taken branch lines of one file."""

    name: str
    missed_lines: tuple[int, ...]
    partial_branches: tuple[int, ...]

    @property
    def complete(self) -> bool:
        return not self.missed_lines and not self.partial_branches


def parse_report(report: Path) -> list[FileCoverage]:
    """Every measured file of a Cobertura report (several classes of one file are merged)."""
    # Same input as the import above.
    tree = ET.parse(report)  # noqa: S314  # nosec B314
    missed: dict[str, set[int]] = {}
    partial: dict[str, set[int]] = {}
    for cls in tree.iter("class"):
        name = cls.attrib["filename"]
        missed.setdefault(name, set())
        partial.setdefault(name, set())
        for line in cls.iter("line"):
            number = int(line.attrib["number"])
            if int(line.attrib["hits"]) == 0:
                missed[name].add(number)
            match = _CONDITIONS.search(line.attrib.get("condition-coverage", ""))
            if match and match.group(1) != match.group(2):
                partial[name].add(number)
    return [
        FileCoverage(name, tuple(sorted(missed[name])), tuple(sorted(partial[name])))
        for name in sorted(missed)
    ]


def source_files(root: Path) -> list[str]:
    """Every .py file of the package, relative to root (server/), as the report names them."""
    return sorted(p.relative_to(root).as_posix() for p in (root / PACKAGE).rglob("*.py"))


def pragma_lines(path: Path) -> list[int]:
    """Lines of path carrying a coverage exclusion pragma."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return [number for number, line in enumerate(lines, 1) if _PRAGMA.search(line)]


def check(
    files: list[FileCoverage], critical: dict[str, str], root: Path
) -> tuple[list[str], list[str]]:
    """Returns (failures, notes): one failure per critical file not fully covered."""
    failures: list[str] = []
    notes: list[str] = []
    measured = {f.name: f for f in files}
    if not any(name.startswith(f"{PACKAGE}/") for name in measured):
        failures.append(
            f"no file of the report starts with {PACKAGE}/: the report layout changed, "
            "fix PACKAGE before trusting this gate"
        )
    on_disk = source_files(root)
    for area, pattern in critical.items():
        matched = [name for name in on_disk if fnmatchcase(name, pattern)]
        if not matched:
            notes.append(f"{area}: no file matches {pattern} yet")
            continue
        notes.append(f"{area}: {len(matched)} file(s) at 100 %")
        for name in matched:
            failures.extend(_file_failures(name, area, measured.get(name), root))
    return failures, notes


def _file_failures(name: str, area: str, cov: FileCoverage | None, root: Path) -> list[str]:
    failures: list[str] = []
    if cov is None:
        failures.append(f"{name} ({area}): not in the coverage report (never measured)")
    elif not cov.complete:
        failures.append(
            f"{name} ({area}): missed lines {list(cov.missed_lines)}, "
            f"partial branches on lines {list(cov.partial_branches)}"
        )
    if pragmas := pragma_lines(root / name):
        failures.append(
            f"{name} ({area}): coverage exclusion pragma on lines {pragmas}; "
            "critical code is covered by tests, never excluded"
        )
    return failures


def main(argv: list[str]) -> int:
    """Usage: critical_coverage.py [REPORT [ROOT]], ROOT being server/ (default: cwd)."""
    report = Path(argv[1]) if len(argv) > 1 else Path("reports/coverage.xml")
    root = Path(argv[2]) if len(argv) > 2 else Path()  # noqa: PLR2004
    if not report.is_file():
        sys.stderr.write(f"critical coverage: {report} not found; run pytest first\n")
        return 2
    failures, notes = check(parse_report(report), CRITICAL, root)
    if failures:
        sys.stderr.write("Critical modules below 100 % line and branch coverage:\n")
        sys.stderr.writelines(f"  {failure}\n" for failure in failures)
        return 1
    sys.stdout.writelines(f"critical coverage: {note}\n" for note in notes)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
