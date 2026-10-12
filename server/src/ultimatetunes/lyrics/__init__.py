# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Synced and plain lyrics (SPEC RF-07). Owned by PLAN T10.

- `lrc`: LRC parsing (synced lines with timings) and plain-text splitting, tolerant of
  malformed input.
- `lrclib`: the LRCLIB client (httpx, `https://lrclib.net` only, identifying User-Agent).
- `repository`: the `lyrics` table and the track lookup it needs.
- `service`: stored-first lookups, LRCLIB etiquette (rate limit, `Retry-After` backoff,
  negative cache) and the OpenSubsonic `structuredLyrics` payload.
"""
