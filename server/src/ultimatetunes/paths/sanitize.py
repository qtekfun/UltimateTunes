# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""One safe path component (a directory or file name) from untrusted metadata.

Metadata comes from YouTube Music and MusicBrainz, so it is untrusted: it may hold `/`, `..`,
NUL, control characters, bidi overrides, zero-width characters, Windows reserved names or
names longer than any filesystem allows. `sanitize_component` turns any string into a name
that is never empty, never `.` or `..`, holds no separator and fits in `max_bytes` of UTF-8:

1. NFKC normalization first, so look-alikes that fold to `/`, `\\`, `.` or `:` (fullwidth
   solidus, one/two dot leaders, ...) are caught by the next steps.
2. Characters forbidden on common filesystems (`/ \\ : * ? " < > |`) become `_`; control
   characters become a space; format, surrogate, private-use and unassigned characters
   (zero-width, bidi overrides, BOM, ...) are dropped; any Unicode space becomes a space.
3. Whitespace runs collapse to one space; the result is cut to `max_bytes` on a character
   boundary; leading and trailing spaces and dots are stripped (no hidden files, no `..`,
   no trailing dot that Windows/SMB clients choke on).
4. Windows reserved device names (`CON`, `NUL`, `COM1`, ..., with or without an extension)
   get a `_` prefix, since `/music` may be shared over SMB.
5. An empty result becomes `fallback` (a constant chosen by the caller).

The result still goes through `LibraryStore` (`check`/`local_path`), which is the floor.
"""

import unicodedata

# File and directory names are limited to 255 bytes on every common Linux filesystem; stay
# well under it so suffixes (" (2)", the extension) and temporary names always fit.
MAX_COMPONENT_BYTES = 180
_FORBIDDEN = frozenset('/\\:*?"<>|')
_DROPPED_CATEGORIES = frozenset({"Cf", "Cs", "Co", "Cn", "Zl", "Zp"})
_DIGITS = "123456789\u00b9\u00b2\u00b3"
_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"} | {f"COM{d}" for d in _DIGITS} | {f"LPT{d}" for d in _DIGITS}
)


def _clean_chars(text: str) -> str:
    out: list[str] = []
    for ch in unicodedata.normalize("NFKC", text):
        category = unicodedata.category(ch)
        if ch in _FORBIDDEN:
            out.append("_")
        elif category in _DROPPED_CATEGORIES:
            continue
        elif category in ("Cc", "Zs"):
            out.append(" ")
        else:
            out.append(ch)
    return " ".join("".join(out).split())


def truncate_utf8(text: str, max_bytes: int) -> str:
    """`text` cut to at most `max_bytes` of UTF-8, never inside a character."""
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text
    return raw[:max_bytes].decode("utf-8", errors="ignore")


def _is_reserved(name: str) -> bool:
    stem = name.split(".", 1)[0].rstrip(" ")
    return stem.upper() in _RESERVED


def sanitize_component(text: str, *, fallback: str, max_bytes: int = MAX_COMPONENT_BYTES) -> str:
    """A safe, non-empty path component from `text` (see the module docstring)."""
    if max_bytes < 2:  # noqa: PLR2004 - room for the reserved-name prefix and one character
        raise ValueError("max_bytes must leave room for at least two bytes")
    if not fallback or _is_reserved(fallback) or _clean_chars(fallback).strip(" .") != fallback:
        raise ValueError("the fallback must be a safe, non-empty name")
    name = truncate_utf8(_clean_chars(text), max_bytes - 1).strip(" .")
    if _is_reserved(name):
        name = f"_{name}"
    return name or fallback
