# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The canary is wired into the api (its area hook). The worker command's factory is checked
in tests/worker/test_loop.py."""

from ultimatetunes import app
from ultimatetunes.canary import web as canary_web


def test_the_api_runs_the_canary_hook() -> None:
    assert canary_web in app.AREAS
