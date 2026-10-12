# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The import URL allowlist (CLAUDE.md security rules: no SSRF, Spotify URLs rejected in v1)."""

import pytest

from ultimatetunes.errors import UnsupportedUrl
from ultimatetunes.imports.urls import playlist_id_from_url


@pytest.mark.parametrize(
    ("url", "playlist_id"),
    [
        ("https://music.youtube.com/playlist?list=PLx9Kd2Lm4Qp7Wz1", "PLx9Kd2Lm4Qp7Wz1"),
        ("https://www.youtube.com/playlist?list=PLabc_-123", "PLabc_-123"),
        ("http://youtube.com/watch?v=Wq5Jd7HsKe2&list=OLAK5uy_abc", "OLAK5uy_abc"),
        ("https://m.youtube.com/playlist?list=PLm1", "PLm1"),
        ("  https://MUSIC.YouTube.com/browse/x?list=VLPLabc  ", "PLabc"),
    ],
)
def test_allowed(url: str, playlist_id: str) -> None:
    assert playlist_id_from_url(url) == playlist_id


@pytest.mark.parametrize(
    "url",
    [
        "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
        "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M",
        "https://youtu.be/Wq5Jd7HsKe2?list=PLabc",
        "https://music.youtube.com.evil.example/playlist?list=PLabc",
        "https://evil.example/?u=https://music.youtube.com/playlist?list=PLabc",
        "ftp://music.youtube.com/playlist?list=PLabc",
        "https://user:pw@music.youtube.com/playlist?list=PLabc",
        "https://music.youtube.com:443/playlist?list=PLabc",
        "https://music.youtube.com:99999/playlist?list=PLabc",
        "https://[::1/playlist?list=PLabc",
        "https://music.youtube.com/playlist",
        "https://music.youtube.com/playlist?list=a&list=b",
        "https://music.youtube.com/playlist?list=P",
        "https://music.youtube.com/playlist?list=PL%2F..%2Fetc",
        "https://music.youtube.com/playlist?list=" + "x" * 2048,
    ],
)
def test_refused(url: str) -> None:
    with pytest.raises(UnsupportedUrl):
        playlist_id_from_url(url)
