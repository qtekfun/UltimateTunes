# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The download worker (no database access). Owned by PLAN T08.

T02 ships:
- `downloader`: the `Downloader` protocol, progress/result records, `DownloadError`, and
  `build_downloader(settings, staging)`, which T08 points at the yt-dlp implementation.
- `fake`: `FakeDownloader`, which writes a short generated WAV file slowly into staging.
T08 adds the worker loop on the internal worker API, yt-dlp and its self-update here.
"""
