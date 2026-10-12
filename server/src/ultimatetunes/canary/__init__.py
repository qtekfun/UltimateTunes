# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The server canary (SPEC section 11, PLAN T19): does YouTube Music still answer the way we
parse it, and does yt-dlp still download?

- `checks.py`: the checks themselves (catalog: search, radio, album page, playlist read;
  download: one fixed Creative Commons track into staging, deleted afterwards).
- `web.py`: the api side, scheduled in the api's lifespan, recorded in `canary_runs`.
- `worker.py`: the worker side, scheduled in the worker loop, reported with its status.
- `cli.py`: `ultimatetunes canary`, one manual run without the api (the GitHub job).

Results show in the admin panel (T15) and failed runs go to the admin's notification target.
"""
