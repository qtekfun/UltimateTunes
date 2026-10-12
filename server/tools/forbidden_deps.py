# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fails if uv.lock resolves a telemetry, analytics or crash-reporting package (CLAUDE.md).

Checks every locked package, runtime and dev groups alike, so a transitive dependency cannot
slip one in either.
"""

import re
import sys
import tomllib
from fnmatch import fnmatchcase
from pathlib import Path

# Normalized (PEP 503) names; fnmatch patterns.
FORBIDDEN = (
    "sentry*",
    "opentelemetry-sdk",
    "opentelemetry-exporter-*",
    "firebase*",
    "google-analytics*",
    "posthog*",
    "mixpanel*",
    "segment-analytics*",
    "analytics-python",
    "datadog*",
    "ddtrace",
    "newrelic*",
    "bugsnag*",
    "rollbar*",
    "logfire*",
    "amplitude*",
    "honeybadger*",
    "elastic-apm",
    "scout-apm",
)

# Allowed although they look related, with the reason.
ALLOWED = {
    # FastAPI depends on the OpenTelemetry *API* only: a no-op unless an SDK and an exporter are
    # installed, and both are forbidden above.
    "opentelemetry-api": "no-op API pulled in by fastapi; the SDK and exporters stay forbidden",
}


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def locked_packages(lock: Path) -> list[str]:
    with lock.open("rb") as f:
        data = tomllib.load(f)
    return sorted({normalize(p["name"]) for p in data.get("package", [])})


def offenders(packages: list[str]) -> list[str]:
    return [
        name
        for name in packages
        if name not in ALLOWED and any(fnmatchcase(name, pattern) for pattern in FORBIDDEN)
    ]


def main(argv: list[str]) -> int:
    lock = Path(argv[1] if len(argv) > 1 else "uv.lock")
    found = offenders(locked_packages(lock))
    if found:
        sys.stderr.write(f"Forbidden telemetry/analytics dependencies in {lock}: {found}\n")
        sys.stderr.write("See CLAUDE.md, Free-software and privacy rules.\n")
        return 1
    sys.stdout.write(f"forbidden dependencies: none in {lock}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
