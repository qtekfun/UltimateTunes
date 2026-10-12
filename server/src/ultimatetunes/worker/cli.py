# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Commands of the worker area (`commands.AREAS`). Owner: PLAN T08."""

from ultimatetunes.commands import CommandRegistry, no_args
from ultimatetunes.settings import Settings


def _worker(settings: Settings) -> int:
    from ultimatetunes.worker.loop import run_worker  # noqa: PLC0415 - only this role needs it

    return run_worker(settings)


def register(registry: CommandRegistry) -> None:
    registry.add("worker", no_args(_worker), help="Run the download worker (no database access)")
