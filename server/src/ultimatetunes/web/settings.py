# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings of the web player (`UT_*` env vars).

- `UT_WEB_ENABLED`: serve `/web` (default true). Off, every `/web` path answers 404.
- `UT_WEB_SESSION_TTL_S`: lifetime of a web player session (default 7 days, at most 30).

The cookies are signed with the admin panel's key (`UT_ADMIN_SESSION_SECRET`, `admin/settings.py`)
under their own salt, so an admin cookie is never a web cookie nor the other way round.
"""

from pydantic import Field

from ultimatetunes.settings import AreaSettings

DAY_S = 24 * 3600


class WebSettings(AreaSettings):
    web_enabled: bool = True
    web_session_ttl_s: int = Field(default=7 * DAY_S, ge=300, le=30 * DAY_S)
