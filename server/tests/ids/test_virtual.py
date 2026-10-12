# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Id parsing per contracts/ids.md: everything malformed is `InvalidId` before any lookup."""

import pytest

from ultimatetunes.errors import InvalidId, spec_for
from ultimatetunes.ids import (
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
from ultimatetunes.ids.virtual import is_browse_id, is_uuid, is_video_id, virtual

UUID = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01b001"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("yt:Qx7Lm2pZ0aB", VirtualId("song", "Qx7Lm2pZ0aB")),
        ("yt:a-b_c-d_e-f", VirtualId("song", "a-b_c-d_e-f")),
        ("ytalbum:MPREb_k3Vd9QmT2xL", VirtualId("album", "MPREb_k3Vd9QmT2xL")),
        ("ytartist:UCq8XbV1r0LwZ5mN3tYp7kQe", VirtualId("artist", "UCq8XbV1r0LwZ5mN3tYp7kQe")),
        ("ytalbum:" + "a" * 64, VirtualId("album", "a" * 64)),
        (UUID, LibraryId(UUID)),
        (UUID.upper(), LibraryId(UUID)),
    ],
)
def test_valid_ids(text: str, expected: LibraryId | VirtualId) -> None:
    assert parse_id(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "yt:",
        "yt:short",
        "yt:Qx7Lm2pZ0aBx",
        "yt:Qx7Lm2pZ0a\n",
        "yt:Qx7Lm2pZ0aB\n",
        " yt:Qx7Lm2pZ0aB",
        "yt:Qx7Lm2pZ0a%",
        "yt:../../etc/pa",
        "YT:Qx7Lm2pZ0aB",
        "ytalbum:",
        "ytalbum:" + "a" * 65,
        "ytalbum:MPREb/x",
        "ytartist:UC q8",
        "ytvideo:Qx7Lm2pZ0aB",
        "spotify:track:1",
        UUID[:-1],
        UUID + "0",
        UUID.replace("-", ""),
        "0199d6a2-4c1e-7b3a-9f10-2a6c8e01b00g",
        "al-" + UUID,
    ],
)
def test_invalid_ids(text: str) -> None:
    with pytest.raises(InvalidId) as raised:
        parse_id(text)
    assert spec_for(raised.value).subsonic_code == 70


def test_parse_kind_keeps_library_and_matching_virtual_ids() -> None:
    assert parse_kind(UUID, "song") == LibraryId(UUID)
    assert parse_kind("yt:Qx7Lm2pZ0aB", "song") == VirtualId("song", "Qx7Lm2pZ0aB")
    assert parse_kind("ytalbum:MPREb_x", "album") == VirtualId("album", "MPREb_x")
    with pytest.raises(InvalidId):
        parse_kind("ytalbum:MPREb_x", "song")
    with pytest.raises(InvalidId):
        parse_kind("yt:Qx7Lm2pZ0aB", "artist")


def test_builders_round_trip() -> None:
    assert song_id("Qx7Lm2pZ0aB") == "yt:Qx7Lm2pZ0aB"
    assert album_id("MPREb_k3Vd9QmT2xL") == "ytalbum:MPREb_k3Vd9QmT2xL"
    assert artist_id("UCq8XbV1r0LwZ5mN3tYp7kQe") == "ytartist:UCq8XbV1r0LwZ5mN3tYp7kQe"
    assert parse_id(song_id("Qx7Lm2pZ0aB")) == virtual("song", "Qx7Lm2pZ0aB")
    with pytest.raises(InvalidId):
        song_id("x")
    with pytest.raises(InvalidId):
        album_id("")
    with pytest.raises(InvalidId):
        artist_id("a b")


def test_predicates() -> None:
    assert is_video_id("Qx7Lm2pZ0aB")
    assert not is_video_id("Qx7Lm2pZ0aB\n")
    assert is_browse_id("MPREb_k3Vd9QmT2xL")
    assert not is_browse_id("")
    assert is_uuid(UUID)
    assert not is_uuid(UUID.upper())


def test_cover_ids() -> None:
    assert cover_id("album", UUID) == f"al-{UUID}"
    assert cover_id("artist", UUID) == f"ar-{UUID}"
    assert cover_id("playlist", UUID) == f"pl-{UUID}"
    with pytest.raises(InvalidId):
        cover_id("album", "../cover.jpg")
    assert parse_cover_id(f"al-{UUID}") == CoverId("album", UUID)
    assert parse_cover_id(f"ar-{UUID.upper()}") == CoverId("artist", UUID)
    assert parse_cover_id(f"pl-{UUID}") == CoverId("playlist", UUID)
    assert parse_cover_id("yt:Qx7Lm2pZ0aB") == CoverId("song", "Qx7Lm2pZ0aB")
    assert parse_cover_id("ytalbum:MPREb_x") == CoverId("external_album", "MPREb_x")
    assert parse_cover_id("ytartist:UCx") == CoverId("external_artist", "UCx")


@pytest.mark.parametrize(
    "text", ["al-", "al-../../etc/passwd", f"xx-{UUID}", UUID, "yt:bad", "", "cover.jpg"]
)
def test_invalid_cover_ids(text: str) -> None:
    with pytest.raises(InvalidId):
        parse_cover_id(text)
