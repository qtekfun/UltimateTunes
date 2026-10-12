# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Commands of the canary area (`commands.AREAS`). Owner: PLAN T19, which adds `canary` (run
the checks once and store the result) here."""

from ultimatetunes.commands import CommandRegistry


def register(registry: CommandRegistry) -> None:
    """No canary command yet."""
