# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`FakeLrclib`: LRCLIB for the test stack (`UT_FAKE_YOUTUBE=1`), with no outbound request.

Every query gets invented synced lyrics built from the title, so the app and third-party clients
show lyrics against the invented library. A title containing "instrumental" is an
instrumental record; one containing "no lyrics" is not found (LRCLIB's 404).
"""

import zlib

from ultimatetunes.lyrics.lrclib import LrclibQuery, LrclibRecord


class FakeLrclib:
    def __init__(self) -> None:
        self.queries: list[LrclibQuery] = []

    def get(self, query: LrclibQuery) -> LrclibRecord | None:
        self.queries.append(query)
        title = query.track_name.lower()
        if "no lyrics" in title:
            return None
        record_id = zlib.crc32(f"{query.artist_name}\n{query.track_name}".encode()) & 0x7FFFFFFF
        if "instrumental" in title:
            return LrclibRecord(record_id, instrumental=True, plain_lyrics=None, synced_lyrics=None)
        lines = [
            f"{query.track_name}, first line",
            f"{query.artist_name} sings the second line",
            "A third line, made up for the test stack",
        ]
        synced = "\n".join(f"[00:{5 * i:02d}.00] {text}" for i, text in enumerate(lines))
        return LrclibRecord(
            record_id, instrumental=False, plain_lyrics="\n".join(lines), synced_lyrics=synced
        )
