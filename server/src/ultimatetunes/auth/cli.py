# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Commands of the auth area (`commands.AREAS`). Owner: PLAN T04, which adds e.g.
`bootstrap-admin` (create the first admin account) here."""

from ultimatetunes.commands import CommandRegistry


def register(registry: CommandRegistry) -> None:
    """No auth command yet."""
