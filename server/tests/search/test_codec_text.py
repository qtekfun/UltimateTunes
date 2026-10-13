# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Cache codec round trips and text normalisation."""

import pytest

from ultimatetunes.search import codec
from ultimatetunes.search.fake import PLAYLIST_ID, FakeMusicCatalog
from ultimatetunes.search.text import like_pattern, normalize, tokens

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_every_record_round_trips() -> None:
    fake = FakeMusicCatalog()
    album = await fake.album("MPREb_k3Vd9QmT2xL")
    artist = await fake.artist("UCq8XbV1r0LwZ5mN3tYp7kQe")
    playlist = await fake.playlist(PLAYLIST_ID)
    tracks = await fake.search_songs("a", 10)
    albums = await fake.search_albums("a", 10)
    artists = await fake.search_artists("a", 10)
    assert codec.decode_album(codec.encode(album)) == album
    assert codec.decode_artist(codec.encode(artist)) == artist
    assert codec.decode_playlist(codec.encode(playlist)) == playlist
    assert codec.decode_track(codec.encode(tracks[0])) == tracks[0]
    assert codec.decode_tracks(codec.encode(tracks)) == tracks
    assert codec.decode_album_refs(codec.encode(albums)) == albums
    assert codec.decode_artist_refs(codec.encode(artists)) == artists
    no_album = tracks[0].__class__(tracks[0].video_id, "x", (), None, None, False, None, None)
    assert codec.decode_track(codec.encode(no_album)) == no_album
    moods = await fake.moods()
    assert codec.decode_moods(codec.encode(moods)) == moods


def test_encode_refuses_other_values() -> None:
    with pytest.raises(TypeError):
        codec.encode({"a": 1})
    with pytest.raises(TypeError):
        codec.encode(FakeMusicCatalog)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("  Héroes del Silencio — Entre dos Tierras!", "heroes del silencio entre dos tierras"),
        ("GUNS N' ROSES", "guns n roses"),
        ("AC/DC", "ac dc"),
        ("\uff26\uff55\uff4c\uff4c\u3000\uff57\uff49\uff44\uff54\uff48", "full width"),
        ("Straße", "strasse"),
        ("snake_case", "snake_case"),
        ("", ""),
        ("!!!", ""),
    ],
)
def test_normalize(text: str, expected: str) -> None:
    assert normalize(text) == expected


def test_tokens() -> None:
    assert tokens("The the  THE paper") == ["the", "paper"]
    assert tokens("a b c d e f g h i j") == ["a", "b", "c", "d", "e", "f", "g", "h"]
    assert tokens("  ") == []


def test_like_pattern_escapes_wildcards() -> None:
    assert like_pattern("a_b%c\\") == "%a\\_b\\%c\\\\%"
