# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The download worker (no database access). Owned by PLAN T08.

T02 ships:
- `downloader`: the `Downloader` protocol, progress/result records, `DownloadError`, and
  `build_downloader(settings, staging)`, which T08 points at the real implementation.
- `fake`: `FakeDownloader`, which writes a short silent Ogg/Opus file (`assets/`) slowly into
  staging.
- `loop`: the worker main loop (idles until SIGTERM for now), `cli`: the `worker` command,
  `settings`: `WorkerSettings` (`UT_*` env vars).
T08 adds the loop on the internal worker API, the real downloader and its self-update here.
"""
