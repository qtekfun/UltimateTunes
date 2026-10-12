# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Playlists: ownership and visibility, songs (library and `yt:`), edits, limits."""

from typing import Any

import pytest

from tests.library.harness import Harness
from tests.subsonic.test_annotation import jobs

UNKNOWN = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01ffff"


def create(lib: Harness, key: str = "utk_ana", **params: Any) -> dict[str, Any]:
    r = lib.rest("createPlaylist", key=key, **params)
    body: dict[str, Any] = r.json()["subsonic-response"]
    assert body["status"] == "ok", body
    playlist: dict[str, Any] = body["playlist"]
    return playlist


def entries(lib: Harness, playlist: str, key: str = "utk_ana") -> list[str]:
    body = lib.ok("getPlaylist", "GetPlaylistResponse", id=playlist, key=key)
    return [e["id"] for e in body["playlist"].get("entry", [])]


def test_create_with_library_and_external_songs(lib: Harness) -> None:
    ids = lib.ids()
    playlist = create(
        lib, name="  Sunday Morning ", songId=[ids["Brasas"], "yt:Qx7Lm2pZ0aB", ids["Tidewater"]]
    )
    assert playlist["name"] == "Sunday Morning"
    assert playlist["owner"] == "ana"
    assert playlist["public"] is False
    assert playlist["readonly"] is False
    assert playlist["songCount"] == 3
    assert playlist["duration"] == 3 + 262 + 1
    assert playlist["coverArt"] == f"pl-{playlist['id']}"
    assert [e["id"] for e in playlist["entry"]] == [
        ids["Brasas"],
        "yt:Qx7Lm2pZ0aB",
        ids["Tidewater"],
    ]
    assert jobs(lib) == [("Qx7Lm2pZ0aB", "queued", 30)]
    xml = lib.rest("getPlaylist", fmt="xml", id=playlist["id"]).text
    assert xml.count("<entry ") == 3


def test_visibility_and_ownership(lib: Harness) -> None:
    ids = lib.ids()
    mine = create(lib, name="Mine", songId=ids["Brasas"])["id"]
    lists = lib.ok("getPlaylists", "GetPlaylistsResponse")["playlists"]["playlist"]
    assert [p["id"] for p in lists] == [mine]
    assert lib.ok("getPlaylists", key="utk_bob")["playlists"] == {"playlist": []}
    assert lib.error("getPlaylist", id=mine, key="utk_bob") == 70
    assert lib.error("updatePlaylist", playlistId=mine, name="x", key="utk_bob") == 70
    lib.ok("updatePlaylist", "EmptyResponse", playlistId=mine, public="true", comment="Hi")
    shared = lib.ok("getPlaylists", key="utk_bob")["playlists"]["playlist"]
    assert [(p["id"], p["readonly"], p["comment"]) for p in shared] == [(mine, True, "Hi")]
    assert entries(lib, mine, "utk_bob") == [ids["Brasas"]]
    assert lib.error("updatePlaylist", playlistId=mine, name="x", key="utk_bob") == 50
    assert lib.error("deletePlaylist", id=mine, key="utk_bob") == 50
    assert (
        lib.error("createPlaylist", playlistId=mine, songId=ids["Tidewater"], key="utk_bob") == 50
    )
    assert lib.error("getPlaylists", username="bob") == 50
    assert lib.ok("getPlaylists", username="ANA")["playlists"]["playlist"][0]["id"] == mine


def test_update_songs(lib: Harness) -> None:
    ids = lib.ids()
    playlist = create(lib, name="Edit", songId=[ids["Brasas"], ids["Tidewater"]])["id"]
    lib.ok(
        "updatePlaylist",
        playlistId=playlist,
        songIdToAdd=[ids["Lighthouse Keeper"], "yt:Rb8Tn3ZcYv0"],
        songIndexToRemove=["0"],
        name="Edited",
        public="false",
    )
    assert entries(lib, playlist) == [ids["Tidewater"], ids["Lighthouse Keeper"], "yt:Rb8Tn3ZcYv0"]
    body = lib.ok("getPlaylist", id=playlist)["playlist"]
    assert body["name"] == "Edited"
    lib.ok("updatePlaylist", playlistId=playlist, songIndexToRemove=["2", "0"])
    assert entries(lib, playlist) == [ids["Lighthouse Keeper"]]
    # createPlaylist with playlistId replaces the songs (name optional).
    replaced = create(lib, playlistId=playlist, songId=[ids["Brasas"], ids["Brasas"]])
    assert [e["id"] for e in replaced["entry"]] == [ids["Brasas"], ids["Brasas"]]
    assert replaced["name"] == "Edited"
    # Nothing changes: still fine.
    lib.ok("updatePlaylist", playlistId=playlist)


@pytest.mark.parametrize(
    ("endpoint", "params", "expected"),
    [
        ("createPlaylist", {}, 0),
        ("createPlaylist", {"name": "   "}, 0),
        ("createPlaylist", {"name": "x" * 201}, 0),
        ("createPlaylist", {"name": "x", "songId": UNKNOWN}, 70),
        ("createPlaylist", {"name": "x", "songId": "ytalbum:MPREb_k3Vd9QmT2xL"}, 70),
        ("createPlaylist", {"playlistId": UNKNOWN}, 70),
        ("createPlaylist", {"playlistId": "yt:Qx7Lm2pZ0aB"}, 70),
        ("getPlaylist", {"id": UNKNOWN}, 70),
        ("getPlaylist", {}, 10),
        ("deletePlaylist", {"id": UNKNOWN}, 70),
        ("updatePlaylist", {}, 10),
        ("updatePlaylist", {"playlistId": "PL", "songIndexToRemove": "5"}, 0),
        ("updatePlaylist", {"playlistId": "PL", "songIndexToRemove": "x"}, 0),
        ("updatePlaylist", {"playlistId": "PL", "public": "maybe"}, 0),
        ("updatePlaylist", {"playlistId": "PL", "comment": "c" * 2001}, 0),
        ("updatePlaylist", {"playlistId": "PL", "songIdToAdd": UNKNOWN}, 70),
    ],
)
def test_playlist_errors(
    lib: Harness, endpoint: str, params: dict[str, str], expected: int
) -> None:
    playlist = create(lib, name="Base", songId=lib.ids()["Brasas"])["id"]
    resolved = {k: (playlist if v == "PL" else v) for k, v in params.items()}
    assert lib.error(endpoint, **resolved) == expected
    assert entries(lib, playlist) == [lib.ids()["Brasas"]]


def test_playlist_size_limit(lib: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    from ultimatetunes.library import playlists  # noqa: PLC0415

    monkeypatch.setattr(playlists, "MAX_TRACKS", 2)
    brasas = lib.ids()["Brasas"]
    playlist = create(lib, name="Small", songId=[brasas, brasas])["id"]
    assert lib.error("updatePlaylist", playlistId=playlist, songIdToAdd=brasas) == 0
    assert lib.error("createPlaylist", name="Big", songId=[brasas] * 3) == 0


def test_delete(lib: Harness) -> None:
    playlist = create(lib, name="Gone", songId=lib.ids()["Brasas"])["id"]
    lib.ok("deletePlaylist", "EmptyResponse", id=playlist)
    assert lib.error("getPlaylist", id=playlist) == 70
    assert lib.one("SELECT COUNT(*) FROM playlist_tracks") == 0
