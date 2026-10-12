# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings of the worker role (`UT_*` env vars). Owner: PLAN T08, which adds the rest
(lease length, poll interval, downloader settings, yt-dlp update channel, ...)."""

from ultimatetunes.settings import AreaSettings


class WorkerSettings(AreaSettings):
    # The api's internal worker API (internal Docker network, single listener in v1).
    api_url: str = "http://api:8044"
    # Stable id of this worker process; the hostname and pid when unset.
    worker_id: str | None = None
