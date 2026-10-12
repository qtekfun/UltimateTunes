# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Identifiers (contracts/ids.md). Owned by PLAN T06, 100 % coverage.

- `uuid7.new_id`: library ids (UUIDv7 from the injectable clock).
- `virtual`: parsing of library, virtual (`yt:`, `ytalbum:`, `ytartist:`) and cover art ids.
- `resolve`: virtual ↔ library resolution and the materialization of a `yt:` song.

`resolve` is imported from its own module (`ultimatetunes.ids.resolve`), not re-exported here:
it depends on the catalog records, and `new_id` must stay importable from anywhere.
"""

from ultimatetunes.ids.uuid7 import new_id
from ultimatetunes.ids.virtual import (
    ALBUM_PREFIX,
    ARTIST_PREFIX,
    SONG_PREFIX,
    CoverId,
    LibraryId,
    VirtualId,
    album_id,
    artist_id,
    cover_id,
    parse_cover_id,
    parse_id,
    parse_kind,
    song_id,
)

__all__ = [
    "ALBUM_PREFIX",
    "ARTIST_PREFIX",
    "SONG_PREFIX",
    "CoverId",
    "LibraryId",
    "VirtualId",
    "album_id",
    "artist_id",
    "cover_id",
    "new_id",
    "parse_cover_id",
    "parse_id",
    "parse_kind",
    "song_id",
]
