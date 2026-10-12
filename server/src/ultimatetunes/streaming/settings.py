# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings of streaming while downloading (`UT_*` env vars). Owner: PLAN T16.

- `UT_MAX_LISTENERS_PER_JOB` / `UT_MAX_LISTENERS_PER_KEY`: listener caps of an in-flight `yt:`
  stream (contracts/errors.md); beyond them, HTTP 503 with `Retry-After`
  (`UT_LISTENER_RETRY_AFTER_S`).
- `UT_STREAM_POLL_INTERVAL_S`: how often a job with listeners is re-read from the database
  when no progress report reached this api process (e.g. another replica stored it). Reports
  that reach this process wake its listeners at once.
- `UT_STAGING_SWEEP_INTERVAL_S`: how often the api deletes the staging directories nobody
  needs any more (0 switches the periodic sweep off; the cleanup after the last listener and
  after `complete`/`fail` still runs).
"""

from pydantic import Field

from ultimatetunes.settings import AreaSettings


class StreamingSettings(AreaSettings):
    # Listener caps of an in-flight `yt:` stream (contracts/errors.md): beyond them, HTTP 503.
    max_listeners_per_job: int = Field(default=8, ge=1)
    max_listeners_per_key: int = Field(default=4, ge=1)
    listener_retry_after_s: int = Field(default=5, ge=1, le=300)
    stream_poll_interval_s: float = Field(default=0.25, gt=0, le=0.5)
    staging_sweep_interval_s: float = Field(default=300.0, ge=0)
