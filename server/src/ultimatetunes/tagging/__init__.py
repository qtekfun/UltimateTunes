# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tagging and archive (PLAN T09), run by the worker between download and `complete`.

- `archiver`: `TaggingArchiver`, the worker's `Archiver` (build, register, album gain, move).
- `ffmpeg`: probe, remux by stream copy, EBU R128 loudness for ReplayGain (argument lists).
- `tags`: mutagen tags for Ogg/Opus and M4A.
- `musicbrainz` + `matching`: recording search (1 req/s) and the strong/weak match decision.
- `covers`: Cover Art Archive, else the YouTube thumbnail (approved hosts only).
- `ratelimit`: the worker's in-process `RateLimiter`.
- `model`, `settings`: records and `TaggingSettings`.

File names come from `ultimatetunes.paths` (the path sanitizer).
"""
