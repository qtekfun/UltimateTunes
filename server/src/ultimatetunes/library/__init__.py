# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The library (artists, albums, tracks, scan of `/music`). Owned by PLAN T05.

- `scan`: registers the audio files of `/music` (startup scan in `web`, command in `cli`).
- `repository`, `render`, `songs`: browsing reads and their OpenSubsonic shapes.
- `stream`, `covers`: library files with HTTP Range, cover art (library and external).
- `annotate`, `playlists`, `playqueue`: per-user stars, scrobbles, playlists, saved queue.
- `internal_api`: the `/internal/v1/library/*` stubs the worker calls to register archived
  files (T02 stubs, not part of PLAN T05).
"""
