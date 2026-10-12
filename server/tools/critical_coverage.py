# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fails unless every critical module has 100 % line and branch coverage (CLAUDE.md, Quality).

Reads the Cobertura report pytest-cov writes (reports/coverage.xml). The critical areas are listed
before their code exists: a pattern that matches no file yet is reported and skipped, and it is
enforced from the moment its first file appears.
"""

import re
import sys
import xml.etree.ElementTree as ET  # nosec B405 - our own coverage report, not untrusted input
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path

# fnmatch patterns over the report's file names (relative to server/); "*" also matches "/".
CRITICAL = {
    "auth (API keys, passwords, OpenSubsonic auth rules)": "src/ultimatetunes/auth/*",
    "rate limiter": "src/ultimatetunes/*rate*limit*",
    "id resolution (yt: <-> library)": "src/ultimatetunes/ids/*",
    "path sanitizer": "src/ultimatetunes/paths/*",
    "job state machine": "src/ultimatetunes/jobs/state*",
    "streaming-while-downloading state machine": "src/ultimatetunes/streaming/state*",
}

_CONDITIONS = re.compile(r"\((\d+)/(\d+)\)")


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
    tree = ET.parse(report)  # noqa: S314  # nosec B314 - see the import
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


def check(files: list[FileCoverage], critical: dict[str, str]) -> tuple[list[str], list[str]]:
    """Returns (failures, notes): one failure per incomplete critical file."""
    failures: list[str] = []
    notes: list[str] = []
    for area, pattern in critical.items():
        matched = [f for f in files if fnmatchcase(f.name, pattern)]
        if not matched:
            notes.append(f"{area}: no file matches {pattern} yet")
            continue
        notes.append(f"{area}: {len(matched)} file(s) at 100 %")
        failures.extend(
            f"{f.name} ({area}): missed lines {list(f.missed_lines)}, "
            f"partial branches on lines {list(f.partial_branches)}"
            for f in matched
            if not f.complete
        )
    return failures, notes


def main(argv: list[str]) -> int:
    report = Path(argv[1] if len(argv) > 1 else "reports/coverage.xml")
    if not report.is_file():
        sys.stderr.write(f"critical coverage: {report} not found; run pytest first\n")
        return 2
    failures, notes = check(parse_report(report), CRITICAL)
    if failures:
        sys.stderr.write("Critical modules below 100 % line and branch coverage:\n")
        sys.stderr.writelines(f"  {failure}\n" for failure in failures)
        return 1
    sys.stdout.writelines(f"critical coverage: {note}\n" for note in notes)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
