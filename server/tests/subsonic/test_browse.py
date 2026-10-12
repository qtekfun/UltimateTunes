# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Browsing and lists, JSON and XML, checked against the contract's schemas."""

from typing import Any

import pytest

from tests.library.harness import LIGHTHOUSE_MBID, Harness
from tests.library.media import mp3_tags, write_mp3
from ultimatetunes.errors import UpstreamUnavailable
from ultimatetunes.library.scan import LibraryScanner
from ultimatetunes.search.library import LibraryArtist
from ultimatetunes.subsonic.routes.browse import index_name

ORCHARD = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01c0cc"
NOW = "2026-10-12T08:00:00.000Z"


def pending_orchard(lib: Harness) -> None:
    """`yt:Rb8Tn3ZcYv0` (Glass Orchard) requested, not archived yet."""
    with lib.services.db.transaction() as conn:
        conn.execute(
            "INSERT INTO tracks (id, status, title, title_norm, artist_name, album_name,"
            " duration_ms, yt_video_id, yt_album_browse_id, yt_artist_channel_id, created_at,"
            " updated_at) VALUES (?, 'pending', 'Glass Orchard', 'glass orchard',"
            " 'The Paper Lanterns', 'Lanterns at Dusk', 198000, 'Rb8Tn3ZcYv0',"
            " 'MPREb_k3Vd9QmT2xL', 'UCq8XbV1r0LwZ5mN3tYp7kQe', ?, ?)",
            (ORCHARD, NOW, NOW),
        )
        conn.execute(
            "INSERT INTO track_aliases (alias, track_id, created_at) VALUES (?, ?, ?)",
            ("yt:Rb8Tn3ZcYv0", ORCHARD, NOW),
        )


def archive_low_tide(lib: Harness) -> str:
    """Tidewater stands in for the archived `yt:Fk2Lp9QwXa1` (Low Tide Letters)."""
    tidewater = lib.ids()["Tidewater"]
    with lib.services.db.transaction() as conn:
        conn.execute(
            "INSERT INTO track_aliases (alias, track_id, created_at) VALUES (?, ?, ?)",
            ("yt:Fk2Lp9QwXa1", tidewater, NOW),
        )
    return tidewater


def test_get_artists(lib: Harness) -> None:
    body = lib.ok("getArtists", "GetArtistsResponse")["artists"]
    assert body["ignoredArticles"] == "The El La Los Las Le Les"
    assert [i["name"] for i in body["index"]] == ["M", "P"]
    lanterns = body["index"][1]["artist"][0]
    assert lanterns["name"] == "The Paper Lanterns"
    assert lanterns["albumCount"] == 1
    assert lanterns["coverArt"] == f"ar-{lanterns['id']}"
    xml = lib.rest("getArtists", fmt="xml").text
    assert '<index name="M">' in xml


def test_index_names() -> None:
    def artist(name: str, sort: str | None = None) -> LibraryArtist:
        return LibraryArtist("id", name, sort, None, 0, None)

    assert index_name(artist("The Paper Lanterns")) == "P"
    assert index_name(artist("Los Ángeles Azules")) == "A"
    assert index_name(artist("Él", None)) == "E"
    assert index_name(artist("2 Brothers")) == "#"
    assert index_name(artist("x", "Zed")) == "Z"
    assert index_name(artist("The")) == "T"


def test_get_artist_library(lib: Harness) -> None:
    lanterns = lib.ids()["The Paper Lanterns"]
    artist = lib.ok("getArtist", "GetArtistResponse", id=lanterns)["artist"]
    assert artist["id"] == lanterns
    (album,) = artist["album"]
    assert album["name"] == "Harbour Lights"
    assert album["songCount"] == 2
    assert album["year"] == 2023
    assert album["genres"] == [{"name": "Indie Pop"}]
    assert album["playCount"] == 0
    assert lib.error("getArtist", id="0199d6a2-4c1e-7b3a-9f10-2a6c8e01ffff") == 70
    assert lib.error("getArtist", id="yt:Qx7Lm2pZ0aB") == 70
    assert lib.error("getArtist") == 10


def test_get_artist_external(lib: Harness) -> None:
    artist = lib.ok("getArtist", "GetArtistResponse", id="ytartist:UCq8XbV1r0LwZ5mN3tYp7kQe")
    body = artist["artist"]
    assert body["id"] == "ytartist:UCq8XbV1r0LwZ5mN3tYp7kQe"
    assert body["coverArt"] == body["id"]
    assert [a["id"] for a in body["album"]] == ["ytalbum:MPREb_k3Vd9QmT2xL"]
    # An album already in the library (same browse id) shows as the library album.
    with lib.services.db.transaction() as conn:
        conn.execute(
            "UPDATE albums SET yt_browse_id = 'MPREb_k3Vd9QmT2xL' WHERE name = 'Harbour Lights'"
        )
    body = lib.ok("getArtist", "GetArtistResponse", id="ytartist:UCq8XbV1r0LwZ5mN3tYp7kQe")
    assert [a["id"] for a in body["artist"]["album"]] == [lib.ids()["Harbour Lights"]]
    assert lib.error("getArtist", id="ytartist:UCunknown") == 70
    lib.catalog.fail_with = UpstreamUnavailable()
    assert lib.error("getArtist", id="ytartist:UCq8XbV1r0LwZ5mN3tYp7kQe") == 0


def test_get_album_library(lib: Harness) -> None:
    album_id = lib.ids()["Harbour Lights"]
    album = lib.ok("getAlbum", "GetAlbumResponse", id=album_id)["album"]
    assert album["songCount"] == 2
    assert album["duration"] == 3
    assert album["coverArt"] == f"al-{album_id}"
    first, second = album["song"]
    assert (first["title"], second["title"]) == ("Lighthouse Keeper", "Tidewater")
    assert first["track"] == 1
    assert first["musicBrainzId"] == LIGHTHOUSE_MBID
    assert first["replayGain"] == {"trackGain": 2.89, "trackPeak": 0.988}
    assert second["replayGain"] == {"trackGain": -6.4, "albumGain": -6.85}
    assert first["suffix"] == "opus"
    assert first["contentType"] == "audio/ogg"
    assert first["path"] == "The Paper Lanterns/Harbour Lights/01 - Lighthouse Keeper.opus"
    xml = lib.rest("getAlbum", fmt="xml", id=album_id).text
    assert '<replayGain trackGain="2.89" trackPeak="0.988"/>' in xml
    assert lib.error("getAlbum", id=album_id.upper().replace("-", "")) == 70
    assert lib.error("getAlbum", id="0199d6a2-4c1e-7b3a-9f10-2a6c8e01ffff") == 70
    # Upper case UUIDs are accepted.
    assert lib.ok("getAlbum", id=album_id.upper())["album"]["id"] == album_id


def test_get_album_external(lib: Harness) -> None:
    pending_orchard(lib)
    tidewater = archive_low_tide(lib)
    album = lib.ok("getAlbum", "GetAlbumResponse", id="ytalbum:MPREb_k3Vd9QmT2xL")["album"]
    assert album["id"] == "ytalbum:MPREb_k3Vd9QmT2xL"
    assert album["songCount"] == 4
    assert album["duration"] == 214 + 198 + 241 + 262
    assert [s["id"] for s in album["song"]] == [
        tidewater,
        "yt:Rb8Tn3ZcYv0",
        "yt:Wq5Jd7HsKe2",
        "yt:Qx7Lm2pZ0aB",
    ]
    assert album["song"][1]["replayGain"] == {}
    assert lib.error("getAlbum", id="ytalbum:MPREb_unknown") == 70


def test_get_song(lib: Harness) -> None:
    song = lib.ids()["Brasas"]
    body = lib.ok("getSong", "GetSongResponse", id=song)["song"]
    assert body["title"] == "Brasas"
    assert body["albumArtists"] == [{"id": lib.ids()["Marisol Vega"], "name": "Marisol Vega"}]
    assert body["genre"] == "Latin Pop"
    pending_orchard(lib)
    pending = lib.ok("getSong", "GetSongResponse", id="yt:Rb8Tn3ZcYv0")["song"]
    assert pending["id"] == "yt:Rb8Tn3ZcYv0"
    assert pending["album"] == "Lanterns at Dusk"
    assert pending["duration"] == 198
    assert lib.ok("getSong", id=ORCHARD)["song"]["id"] == "yt:Rb8Tn3ZcYv0"
    external = lib.ok("getSong", "GetSongResponse", id="yt:Qx7Lm2pZ0aB")["song"]
    assert external["title"] == "Paper Moons (Live)"
    assert external["coverArt"] == "yt:Qx7Lm2pZ0aB"
    assert lib.error("getSong", id="yt:AAAAAAAAAAA") == 70
    assert lib.error("getSong", id="yt:short") == 70
    assert lib.error("getSong", id="ytalbum:MPREb_k3Vd9QmT2xL") == 70
    assert lib.error("getSong", id="0199d6a2-4c1e-7b3a-9f10-2a6c8e01ffff") == 70


def test_get_song_of_a_merged_or_broken_track(lib: Harness) -> None:
    brasas = lib.ids()["Brasas"]
    merged = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01c0dd"
    broken = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01c0ee"
    with lib.services.db.transaction() as conn:
        for track_id, status, into in ((merged, "merged", brasas), (broken, "pending", None)):
            conn.execute(
                "INSERT INTO tracks (id, status, title, title_norm, artist_name, merged_into,"
                " created_at, updated_at) VALUES (?, ?, 'X', 'x', 'A', ?, ?, ?)",
                (track_id, status, into, NOW, NOW),
            )
    assert lib.ok("getSong", id=merged)["song"]["id"] == brasas
    # A pending track without a video id cannot be shown.
    assert lib.error("getSong", id=broken) == 70


def add_albums(lib: Harness) -> None:
    for year, name in ((2019, "Early Days"), (2021, "Middle")):
        write_mp3(
            lib.music / "Neon Harbor" / name / "01.mp3",
            mp3_tags(f"{name} Song", "Neon Harbor", name, year=str(year), genre="Electronic"),
        )
        lib.clock.advance(60)
        LibraryScanner(lib.services.db, lib.services.library, lib.clock).scan()


def album_list(lib: Harness, list_type: str, **params: Any) -> list[str]:
    body = lib.ok("getAlbumList2", "GetAlbumList2Response", type=list_type, **params)
    return [a["name"] for a in body["albumList2"].get("album", [])]


def test_album_lists(lib: Harness) -> None:
    add_albums(lib)
    everything = {"Harbour Lights", "Salt & Ember", "Early Days", "Middle"}
    assert album_list(lib, "alphabeticalByName", size="500") == [
        "Early Days",
        "Harbour Lights",
        "Middle",
        "Salt & Ember",
    ]
    assert album_list(lib, "alphabeticalByArtist") == [
        "Salt & Ember",
        "Early Days",
        "Middle",
        "Harbour Lights",
    ]
    assert album_list(lib, "newest")[:2] == ["Middle", "Early Days"]
    assert set(album_list(lib, "random")) == everything
    assert album_list(lib, "byYear", fromYear="2020", toYear="2025") == [
        "Middle",
        "Harbour Lights",
        "Salt & Ember",
    ]
    assert album_list(lib, "byYear", fromYear="2025", toYear="2020") == [
        "Salt & Ember",
        "Harbour Lights",
        "Middle",
    ]
    assert album_list(lib, "byGenre", genre="Electronic") == ["Early Days", "Middle"]
    assert album_list(lib, "alphabeticalByName", size="1", offset="1") == ["Harbour Lights"]
    assert album_list(lib, "starred") == []
    assert album_list(lib, "recent") == []


def test_album_lists_by_plays_and_stars(lib: Harness) -> None:
    ids = lib.ids()
    lib.ok(
        "scrobble",
        id=[ids["Brasas"], ids["Brasas"], ids["Tidewater"]],
        time=["1000", "2000", "3000"],
    )
    lib.ok("star", albumId=ids["Harbour Lights"])
    assert album_list(lib, "frequent") == ["Salt & Ember", "Harbour Lights"]
    assert album_list(lib, "highest") == ["Salt & Ember", "Harbour Lights"]
    assert album_list(lib, "recent") == ["Harbour Lights", "Salt & Ember"]
    assert album_list(lib, "starred") == ["Harbour Lights"]
    albums = lib.ok("getAlbumList2", type="frequent")["albumList2"]["album"]
    assert albums[0]["playCount"] == 2
    assert albums[0]["played"] == "1970-01-01T00:00:02.000Z"
    assert albums[1]["starred"] == NOW


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({}, 10),
        ({"type": "nope"}, 0),
        ({"type": "newest", "size": "0"}, 0),
        ({"type": "newest", "size": "501"}, 0),
        ({"type": "newest", "size": "x"}, 0),
        ({"type": "newest", "offset": "-1"}, 0),
        ({"type": "byYear", "fromYear": "2000"}, 10),
        ({"type": "byGenre"}, 10),
    ],
)
def test_album_list_errors(lib: Harness, params: dict[str, str], expected: int) -> None:
    assert lib.error("getAlbumList2", **params) == expected


def test_random_songs(lib: Harness) -> None:
    add_albums(lib)
    songs = lib.ok("getRandomSongs", "GetRandomSongsResponse", size="50")["randomSongs"]["song"]
    assert len(songs) == 5
    filtered = lib.ok("getRandomSongs", genre="Electronic", fromYear="2020", toYear="2022")
    assert [s["title"] for s in filtered["randomSongs"]["song"]] == ["Middle Song"]
    assert lib.ok("getRandomSongs", size="0")["randomSongs"] == {"song": []}
    assert len(lib.ok("getRandomSongs")["randomSongs"]["song"]) == 5
    assert lib.error("getRandomSongs", size="501") == 0
    xml = lib.rest("getRandomSongs", fmt="xml", size="1").text
    assert xml.count("<song ") == 1
