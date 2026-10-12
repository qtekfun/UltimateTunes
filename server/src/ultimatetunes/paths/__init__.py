# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Path sanitizer (PLAN T09, 100 % coverage, SECURITY.md): every path built from metadata.

- `sanitize`: one path component from untrusted text (titles, artists, albums).
- `library`: the library layout `Artist/Album/NN - Title.ext` and the album cover path.
"""

from ultimatetunes.paths.library import (
    ARCHIVE_EXTENSIONS,
    COVER_NAME,
    album_dir,
    cover_path,
    library_path,
    track_file_name,
)
from ultimatetunes.paths.sanitize import sanitize_component

__all__ = [
    "ARCHIVE_EXTENSIONS",
    "COVER_NAME",
    "album_dir",
    "cover_path",
    "library_path",
    "sanitize_component",
    "track_file_name",
]
