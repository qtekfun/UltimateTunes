# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The download worker (no database access). Owned by PLAN T08.

- `loop`: the main loop (claim with a lease, heartbeat, download, progress, archive,
  complete/fail), `run_worker` (the `worker` command, SIGTERM-safe) and `build_worker`.
- `client`: `WorkerApi`, the internal worker API over httpx.
- `downloader`: the `Downloader` protocol, progress/result records and `DownloadError`;
  `ytdlp`: `YtDlpDownloader` (the zipapp as a subprocess, spike T03c); `fake`: `FakeDownloader`.
- `ytdlp_runtime`: the zipapp in `/opt/ytdlp`, its seed install and verified self-update.
- `archiver`: the `Archiver` protocol between download and `complete` (implemented by T09).
- `settings`: `WorkerSettings` (`UT_*` env vars).
"""
