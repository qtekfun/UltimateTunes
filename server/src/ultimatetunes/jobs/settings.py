# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings of the jobs area on the api side (`UT_*` env vars). Owner: PLAN T08."""

from pydantic import Field

from ultimatetunes.settings import AreaSettings


class JobsSettings(AreaSettings):
    # `Retry-After` of an empty claim (204): how long an idle worker waits before asking again.
    claim_retry_after_s: int = Field(default=2, ge=1, le=60)
