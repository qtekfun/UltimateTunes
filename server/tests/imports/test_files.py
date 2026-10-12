# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Uploaded playlist files: formats, caps and decoding (SPEC §11, T03d)."""

import json

import pytest

from tests.imports.conftest import fixture_bytes
from ultimatetunes.errors import InvalidParameter, PayloadTooLarge
from ultimatetunes.imports.files import (
    MAX_FIELD_CHARS,
    MAX_FILE_BYTES,
    MAX_ROWS,
    SourceItem,
    decode,
    parse_duration,
    parse_file,
)


def test_generic_csv() -> None:
    data = (
        "\ufeff Title ,ARTIST,album,duration,isrc,extra\r\n"
        "Low Tide Letters,The Paper Lanterns; Guest ;,Lanterns at Dusk,3:34,qz-abc-26-00001,x\r\n"
        '"Comma, Song",Marisol Vega,,214.6,bad\r\n'
        ",,,,\r\n"
        "Short Row,Solo\r\n"
    ).encode()
    parsed = parse_file(data, "csv", filename="C:\\Users\\me\\My_Mix.final.csv")
    assert parsed.name == "My Mix.final"
    assert parsed.items == (
        SourceItem(
            "Low Tide Letters",
            ("The Paper Lanterns", "Guest"),
            "Lanterns at Dusk",
            214,
            "QZABC2600001",
        ),
        SourceItem("Comma, Song", ("Marisol Vega",), None, 215, None),
        SourceItem("Short Row", ("Solo",)),
    )
    assert parsed.items[0].artist_text == "The Paper Lanterns; Guest"
    assert SourceItem("t").artist_text is None


def test_the_fixtures_parse() -> None:
    assert len(parse_file(fixture_bytes("road_trip_50.csv"), "csv").items) == 50
    exportify = parse_file(fixture_bytes("exportify.csv"), "exportify_csv", filename="Mix.csv")
    assert exportify.name == "Mix"
    first = exportify.items[0]
    assert (first.isrc, first.duration_s, first.ref) == (
        "QZDEF2600001",
        209,
        "spotify:track:0aaaaaaaaaaaaaaaaaaaa1",
    )
    assert exportify.items[1].isrc is None
    assert len(exportify.items) == 3  # the local file without a name is skipped


def test_older_exportify_columns() -> None:
    data = (
        b"Track Name,Artist Name(s),Track Duration (ms)\n"
        + b"Song,A,61000\nOther,B,abc\nThird,C,\nHuge,D,"
        + b"9" * 4000
        + b"\n"
    )
    items = parse_file(data, "exportify_csv").items
    assert [i.duration_s for i in items] == [61, None, None, None]


@pytest.mark.parametrize(
    ("value", "seconds"),
    [
        ("214", 214),
        ("0", None),
        ("-3", None),
        ("abc", None),
        ("3:34", 214),
        ("1:03:34", 3814),
        ("3:75", None),
        ("1:75:00", None),
        ("99999999", None),
        (None, None),
    ],
)
def test_parse_duration(value: str | None, seconds: int | None) -> None:
    assert parse_duration(value) == seconds


def test_fields_are_trimmed_and_cut() -> None:
    data = ("title,artist\n" + "x" * (MAX_FIELD_CHARS + 50) + ",  a   b \n").encode()
    item = parse_file(data, "csv").items[0]
    assert len(item.title) == MAX_FIELD_CHARS
    assert item.artists == ("a b",)


def test_decoding() -> None:
    assert decode("\ufeffé".encode()) == "é"
    with pytest.raises(InvalidParameter, match="UTF-8"):
        decode("é".encode("latin-1"))
    with pytest.raises(InvalidParameter, match="text"):
        decode(b"title\x00")
    with pytest.raises(PayloadTooLarge):
        decode(b"x" * (MAX_FILE_BYTES + 1))


def test_row_cap() -> None:
    at_cap = b"title,artist\n" + b"t,a\n" * MAX_ROWS
    assert len(parse_file(at_cap, "csv").items) == MAX_ROWS
    with pytest.raises(PayloadTooLarge, match="5000"):
        parse_file(at_cap + b"t,a\n", "csv")


@pytest.mark.parametrize(
    ("data", "fmt", "message"),
    [
        (b"", "csv", "empty"),
        (b"title,artist\n", "csv", "no tracks"),
        (b"name,artist\nx,y\n", "csv", "missing column"),
        (b"Track Name\nx\n", "exportify_csv", "Artist Name"),
        (b'title,artist\n"' + b"x" * 200_000 + b'",a\n', "csv", "cannot be read"),
        (b"{", "spotify_json", "not valid JSON"),
        (b"[" * 100_000 + b"]" * 100_000, "spotify_json", "not valid JSON"),
        (b"[]", "spotify_json", "no `playlists`"),
        (b'{"playlists": [1, {"items": 3}]}', "spotify_json", "no playlist"),
        (b'{"name": "x", "items": [{"track": {"trackName": 3}}, 7]}', "spotify_json", "no tracks"),
    ],
)
def test_unreadable_files(data: bytes, fmt: str, message: str) -> None:
    with pytest.raises(InvalidParameter, match=message):
        parse_file(data, fmt)  # type: ignore[arg-type]


def test_spotify_json() -> None:
    data = fixture_bytes("spotify_playlists.json")
    parsed = parse_file(data, "spotify_json", name="ROAD TRIP")
    assert parsed.name == "Road Trip"
    assert [i.title for i in parsed.items] == ["Neon Orchard", "Paper Canyon"]
    assert parsed.items[0].ref == "spotify:track:0bbbbbbbbbbbbbbbbbbbb1"
    with pytest.raises(InvalidParameter, match="2 playlists"):
        parse_file(data, "spotify_json", name="Nope")
    single = json.dumps({"items": [{"track": {"trackName": "Song", "artistName": "A"}}]})
    one = parse_file(single.encode(), "spotify_json", filename="Playlist1.json")
    assert one.name == "Playlist1"
    assert one.items == (SourceItem("Song", ("A",)),)
    too_many = json.dumps({"items": [{"track": {"trackName": "s"}}] * (MAX_ROWS + 1)})
    with pytest.raises(PayloadTooLarge):
        parse_file(too_many.encode(), "spotify_json")


def test_names_are_capped() -> None:
    data = json.dumps({"name": "n" * 300, "items": [{"track": {"trackName": "s"}}]})
    name = parse_file(data.encode(), "spotify_json").name
    assert name is not None
    assert len(name) == 200
    assert parse_file(b"title,artist\nt,a\n", "csv", filename="").name is None
    assert parse_file(b"title,artist\nt,a\n", "csv", filename="noext").name == "noext"
