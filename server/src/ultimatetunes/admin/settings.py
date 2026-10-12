# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings of the admin panel (`UT_*` env vars). Owner: PLAN T15, which adds the network
allowlist, session lifetime and the like here (secrets such as the session key come from env
vars or Docker secrets, never from the database)."""

from ultimatetunes.settings import AreaSettings


class AdminSettings(AreaSettings):
    """No admin setting yet."""
