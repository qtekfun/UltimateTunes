# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""ytmusicapi responses → catalog records, on the recorded shapes (tests/search/fixtures)."""

import json
from pathlib import Path

import pytest

from ultimatetunes.search import parse
from ultimatetunes.search.catalog import (
    AlbumRef,
    ArtistRef,
    CatalogAlbumRef,
    CatalogArtistRef,
    CatalogParseError,
    Thumbnail,
)

FIXTURES = Path(__file__).parent / "fixtures"
LANTERNS = ArtistRef("The Paper Lanterns", "UCq8XbV1r0LwZ5mN3tYp7kQe")
HARBOR = ArtistRef("Neon Harbor", "UCn4HbR7oQ2sLx9TzV0eWm3K")
DUSK = AlbumRef("Lanterns at Dusk", "MPREb_k3Vd9QmT2xL")


def load(name: str) -> object:
    data: object = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return data


def test_search_songs() -> None:
    songs = parse.search_songs(load("search_songs.json"))
    assert [s.video_id for s in songs] == ["Fk2Lp9QwXa1", "Qx7Lm2pZ0aB", "Mx1Vb2Nc3Za"]
    first, second, third = songs
    assert first.title == "Low Tide Letters"
    assert first.artists == (LANTERNS,)
    assert first.album == DUSK
    assert first.duration_s == 214
    assert first.video_type == "ATV"
    assert first.year is None
    assert not first.explicit
    # The largest thumbnail, resized to 544 px.
    assert first.thumbnail == Thumbnail(
        "https://yt3.googleusercontent.com/fakeLowTide=w544-h544-l90-rj", 544, 544
    )
    assert second.artists == (LANTERNS, HARBOR)
    assert second.explicit
    assert second.duration_s == 262  # from "4:22"
    # "Various Artists" has no channel id; the thumbnail host is not approved.
    assert third.artists == (ArtistRef("Various Artists", None),)
    assert third.duration_s == 3723  # "1:02:03"
    assert third.thumbnail is None


def test_search_albums() -> None:
    albums = parse.search_albums(load("search_albums.json"))
    assert albums == [
        CatalogAlbumRef(
            "MPREb_k3Vd9QmT2xL",
            "Lanterns at Dusk",
            (LANTERNS,),
            2024,
            Thumbnail("https://yt3.googleusercontent.com/fakeDusk=w544-h544-l90-rj", 544, 544),
        ),
        CatalogAlbumRef(
            "MPREb_Hn2Vq8Lr5Tz",
            "Static Bloom",
            (HARBOR,),
            2025,
            Thumbnail("https://lh3.googleusercontent.com/fakeBloom=s544", 544, 544),
        ),
    ]


def test_search_artists_drop_the_placeholder_avatar() -> None:
    artists = parse.search_artists(load("search_artists.json"))
    assert artists == [
        CatalogArtistRef(
            "UCq8XbV1r0LwZ5mN3tYp7kQe",
            "The Paper Lanterns",
            Thumbnail(
                "https://lh3.googleusercontent.com/fakeLanternsAvatar=w544-h544-p-l90-rj", 544, 544
            ),
        ),
        CatalogArtistRef("UCz1Xy2Wv3Ut4Sr5Qp6On7Ml", "Lantern Look-alike", None),
    ]


def test_album_page() -> None:
    album = parse.album(load("album.json"), "MPREb_k3Vd9QmT2xL")
    assert album.ref.title == "Lanterns at Dusk"
    assert album.ref.year == 2024
    assert album.ref.artists == (LANTERNS,)
    assert album.release_type == "album"
    cover = Thumbnail("https://yt3.googleusercontent.com/fakeDusk=w544-h544-l90-rj", 544, 544)
    assert album.ref.thumbnail == cover
    # The unavailable third track is left out.
    assert [(t.track_number, t.video_id) for t in album.tracks] == [
        (1, "Fk2Lp9QwXa1"),
        (2, "Rb8Tn3ZcYv0"),
    ]
    for track in album.tracks:
        assert track.album == DUSK
        assert track.year == 2024
        assert track.thumbnail == cover
    assert album.tracks[1].video_type == "OMV"


def test_album_without_type_or_thumbnail() -> None:
    data = {"title": "Bare", "tracks": [{"videoId": "Fk2Lp9QwXa1", "title": "x"}]}
    album = parse.album(data, "MPREb_bare")
    assert album.release_type is None
    assert album.ref.thumbnail is None
    assert album.tracks[0].thumbnail is None


def test_artist_page() -> None:
    artist = parse.artist(load("artist.json"), "UCq8XbV1r0LwZ5mN3tYp7kQe")
    assert artist.ref.name == "The Paper Lanterns"
    assert artist.ref.channel_id == "UCq8XbV1r0LwZ5mN3tYp7kQe"
    assert [t.video_id for t in artist.top_tracks] == ["Fk2Lp9QwXa1"]
    assert [(a.browse_id, a.artists) for a in artist.albums] == [
        ("MPREb_k3Vd9QmT2xL", (LANTERNS,)),
        ("MPREb_Sg1Pm2Mn3Lk", (LANTERNS, HARBOR)),
    ]


def test_watch_playlist() -> None:
    tracks = parse.watch_playlist(load("watch_playlist.json"))
    assert [t.video_id for t in tracks] == ["Fk2Lp9QwXa1", "Tz9Kd4Wb7Rc", "Up1Lo2Ad3Zz"]
    assert tracks[0].year == 2024
    assert tracks[0].duration_s == 214
    upload = tracks[2]
    assert upload.album is None
    assert upload.video_type == "UGC"
    assert upload.artists == (ArtistRef("Some uploader", None),)
    assert upload.thumbnail == Thumbnail(
        "https://i.ytimg.com/vi/Up1Lo2Ad3Zz/hqdefault.jpg", 480, 360
    )


def test_playlist_counts_unavailable_entries() -> None:
    playlist = parse.playlist(load("playlist.json"), "PLfakeRoadTrip0123456789abcdefGH")
    assert playlist.title == "Road Trip (fake)"
    assert [t.video_id for t in playlist.tracks] == ["Wq5Jd7HsKe2", "Tz9Kd4Wb7Rc"]
    assert playlist.tracks[0].album is None
    # One null entry, plus two silently missing (trackCount 5, 3 entries).
    assert playlist.unavailable_count == 3


def test_playlist_without_title_or_count() -> None:
    playlist = parse.playlist({"tracks": []}, "PLx")
    assert (playlist.title, playlist.tracks, playlist.unavailable_count) == ("PLx", (), 0)


@pytest.mark.parametrize(
    ("call", "value"),
    [
        (parse.search_songs, {"not": "a list"}),
        (parse.search_albums, None),
        (parse.search_artists, "text"),
        (lambda v: parse.album(v, "MPREb_x"), []),
        (lambda v: parse.album(v, "MPREb_x"), {"tracks": []}),
        (lambda v: parse.artist(v, "UCx"), None),
        (lambda v: parse.artist(v, "UCx"), {"description": "no name"}),
        (parse.watch_playlist, {"tracks": None}),
        (lambda v: parse.playlist(v, "PLx"), {"tracks": "nope"}),
    ],
)
def test_layout_changes_are_parse_errors(call: object, value: object) -> None:
    assert callable(call)
    with pytest.raises(CatalogParseError):
        call(value)


def test_thumbnail_rules() -> None:
    assert parse.thumbnail(None) is None
    assert parse.thumbnail("x") is None
    assert parse.thumbnail([{"width": 10}, "junk"]) is None
    assert parse.thumbnail([{"url": "http://i.ytimg.com/vi/x/hq.jpg"}]) is None
    assert parse.thumbnail([{"url": "https://i.ytimg.com.evil.example/x.jpg"}]) is None
    # i.ytimg.com URLs are kept as they are, unknown sizes too.
    assert parse.thumbnail([{"url": "https://i.ytimg.com/vi/x/hq.jpg"}]) == Thumbnail(
        "https://i.ytimg.com/vi/x/hq.jpg"
    )
    # A Google URL without a size suffix is kept as is.
    assert parse.thumbnail([{"url": "https://yt3.ggpht.com/plain", "width": 88}]) == Thumbnail(
        "https://yt3.ggpht.com/plain", 88, None
    )


def test_field_rules() -> None:
    assert parse.track({"videoId": "Fk2Lp9QwXa1"}) is None
    assert parse.track({"videoId": "Fk2Lp9QwXa1", "title": "   "}) is None
    item = parse.track(
        {
            "videoId": "Fk2Lp9QwXa1",
            "title": " Spaced ",
            "year": 2020,
            "trackNumber": 0,
            "duration_seconds": True,
            "duration": "soon",
            "videoType": "MUSIC_VIDEO_TYPE_PODCAST_EPISODE",
            "album": {"name": "A", "id": "bad id"},
            "artists": [{"name": "X", "id": "bad id"}, {"id": "UCx"}],
        }
    )
    assert item is not None
    assert item.title == "Spaced"
    assert item.year == 2020
    assert item.track_number is None
    assert item.duration_s is None
    assert item.video_type is None
    assert item.album == AlbumRef("A", None)
    assert item.artists == (ArtistRef("X", None),)
    weird = parse.track({"videoId": "Fk2Lp9QwXa1", "title": "t", "year": "MMXX", "album": "s"})
    assert weird is not None
    assert (weird.year, weird.album) == (None, None)
    nameless = parse.track({"videoId": "Fk2Lp9QwXa1", "title": "t", "album": {"id": "MPREb_x"}})
    assert nameless is not None
    assert nameless.album is None
    assert parse.album_ref({"browseId": "bad id", "title": "x"}) is None
    assert parse.artist_ref({"browseId": "UCx"}) is None


def test_thumbnail_keeps_the_largest_whatever_the_order() -> None:
    small_after = [
        {"url": "https://i.ytimg.com/vi/x/big.jpg", "width": 480},
        {"url": "https://i.ytimg.com/vi/x/small.jpg", "width": 120},
    ]
    assert parse.thumbnail(small_after) == Thumbnail("https://i.ytimg.com/vi/x/big.jpg", 480)


def test_artist_page_skips_albums_without_ids() -> None:
    data = {"name": "Band", "albums": {"results": [{"title": "No id"}]}}
    assert parse.artist(data, "UCband").albums == ()
