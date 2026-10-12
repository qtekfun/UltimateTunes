# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Import URLs: the allowlist of CLAUDE.md (YouTube Music and YouTube playlist URLs only).

The URL is parsed locally and never fetched: only the playlist id leaves this module, and the
catalog reads that id through ytmusicapi (no request to an arbitrary URL, so no SSRF). Spotify
URLs, other hosts, other schemes, credentials or ports in the URL, and URLs without a valid
`list=` are `unsupported_url` (v1 imports Spotify playlists from files, SPEC §11, T03d).
"""

import re
from urllib.parse import parse_qs, urlsplit

from ultimatetunes.errors import UnsupportedUrl

ALLOWED_HOSTS = frozenset({"music.youtube.com", "www.youtube.com", "youtube.com", "m.youtube.com"})
MAX_URL_LENGTH = 2048
# The playlist id forms ytmusicapi accepts; a `VL` browse prefix is dropped.
_PLAYLIST_ID = re.compile(r"[A-Za-z0-9_-]{2,64}")


def playlist_id_from_url(url: str) -> str:
    """The playlist id of an allowed YouTube Music / YouTube URL, else `UnsupportedUrl`."""
    if len(url) > MAX_URL_LENGTH:
        raise UnsupportedUrl("The URL is too long")
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        raise UnsupportedUrl("The URL cannot be parsed") from None
    host = (parts.hostname or "").lower()
    if parts.scheme.lower() not in ("https", "http") or host not in ALLOWED_HOSTS:
        raise UnsupportedUrl(
            "Only YouTube Music and YouTube playlist URLs are supported;"
            " import Spotify playlists from an exported file"
        )
    if parts.username is not None or parts.password is not None or port is not None:
        raise UnsupportedUrl("The URL must not carry credentials or a port")
    values = parse_qs(parts.query).get("list", [])
    if len(values) != 1:
        raise UnsupportedUrl("The URL has no playlist (`list=`)")
    playlist_id = values[0].removeprefix("VL")
    if _PLAYLIST_ID.fullmatch(playlist_id) is None:
        raise UnsupportedUrl("The playlist id is not valid")
    return playlist_id
