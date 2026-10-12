# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""No telemetry or analytics package in the lock (tools/forbidden_deps.py)."""

from pathlib import Path

import pytest

from forbidden_deps import locked_packages, main, offenders

LOCK = Path(__file__).parents[2] / "uv.lock"


@pytest.mark.parametrize(
    "name",
    [
        "sentry-sdk",
        "opentelemetry-sdk",
        "opentelemetry-exporter-otlp-proto-http",
        "firebase-admin",
        "google-analytics-data",
        "posthog",
        "mixpanel",
        "segment-analytics-python",
        "datadog",
        "ddtrace",
        "newrelic",
        "bugsnag",
        "rollbar",
        "logfire",
        "amplitude-analytics",
        "honeybadger",
        "elastic-apm",
        "scout-apm",
    ],
)
def test_forbidden_packages_are_flagged(name: str) -> None:
    assert offenders([name, "fastapi"]) == [name]


def test_the_opentelemetry_api_is_allowed() -> None:
    assert offenders(["opentelemetry-api", "fastapi", "httpx"]) == []


def test_lock_names_are_normalized(tmp_path: Path) -> None:
    lock = tmp_path / "uv.lock"
    lock.write_text('[[package]]\nname = "Sentry_SDK"\n\n[[package]]\nname = "fastapi"\n')
    assert locked_packages(lock) == ["fastapi", "sentry-sdk"]
    assert main(["x", str(lock)]) == 1


def test_the_project_lock_is_clean() -> None:
    assert main(["x", str(LOCK)]) == 0
