# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The library layout (RF-04): `Artist/Album/NN - Title.ext`, relative to `/music`.

- `NN` is the track number, two digits (`04`); on a disc after the first it is `D-NN`
  (`2-04`), so two discs never collide. Without a known track number the name is
  `Title.ext`.
- `suffix` disambiguates a name that another track already holds (`Title (Qx7Lm2pZ0aB).opus`).
- Only archive extensions (`opus`, `m4a`, SPEC section 11) are accepted.
- The album cover is `Artist/Album/cover.jpg` (contracts/ids.md, `al-<albumUuid>`).

Every component goes through `sanitize_component`, so the result is a normalized relative
path (no leading `/`, no `.`/`..`, no NUL or backslash) that `LibraryStore` accepts.
"""

from ultimatetunes.errors import PathRejected
from ultimatetunes.paths.sanitize import MAX_COMPONENT_BYTES, sanitize_component

ARCHIVE_EXTENSIONS = frozenset({"opus", "m4a"})
COVER_NAME = "cover.jpg"
UNKNOWN_ARTIST = "Unknown Artist"
UNKNOWN_ALBUM = "Unknown Album"
UNTITLED = "Untitled"
MAX_NUMBER = 999


def _number(value: int | None) -> int | None:
    return value if value is not None and 0 < value <= MAX_NUMBER else None


def album_dir(artist: str, album: str) -> str:
    """`Artist/Album`."""
    return "/".join(
        (
            sanitize_component(artist, fallback=UNKNOWN_ARTIST),
            sanitize_component(album, fallback=UNKNOWN_ALBUM),
        )
    )


def cover_path(artist: str, album: str) -> str:
    """`Artist/Album/cover.jpg`."""
    return f"{album_dir(artist, album)}/{COVER_NAME}"


def track_file_name(
    title: str,
    ext: str,
    *,
    track_number: int | None = None,
    disc_number: int | None = None,
    suffix: str | None = None,
) -> str:
    """`NN - Title.ext` (see the module docstring)."""
    if ext not in ARCHIVE_EXTENSIONS:
        raise PathRejected(f"not an archive extension: {ext[:16]!r}")
    track, disc = _number(track_number), _number(disc_number)
    prefix = ""
    if track is not None:
        prefix = f"{disc}-{track:02d} - " if disc is not None and disc > 1 else f"{track:02d} - "
    if suffix:
        title = f"{title} ({suffix})"
    room = MAX_COMPONENT_BYTES - len(prefix) - len(ext) - 1
    return f"{prefix}{sanitize_component(title, fallback=UNTITLED, max_bytes=room)}.{ext}"


def library_path(  # noqa: PLR0913 - the fields of one file name, keyword-only
    *,
    artist: str,
    album: str,
    title: str,
    ext: str,
    track_number: int | None = None,
    disc_number: int | None = None,
    suffix: str | None = None,
) -> str:
    """`Artist/Album/NN - Title.ext`, relative to the library root."""
    name = track_file_name(
        title, ext, track_number=track_number, disc_number=disc_number, suffix=suffix
    )
    return f"{album_dir(artist, album)}/{name}"
