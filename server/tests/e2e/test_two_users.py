# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Two users on one server (RF-01, RF-09): separate keys, private stars and playlists, one file.

Both users are created in the admin panel and get their own API key with their password; the
song one of them archives is the very library song the other one finds and plays (a track is
downloaded once), while favourites and playlists stay per user.
"""

import pytest

from tests.e2e.conftest import UserFactory

pytestmark = pytest.mark.e2e

VIDEO = "Rb8Tn3ZcYv0"
SONG = f"yt:{VIDEO}"
TITLE = "Glass Orchard"
NOT_FOUND = 70


def starred_ids(starred: dict[str, object]) -> list[str]:
    songs = starred["starred2"].get("song", [])  # type: ignore[attr-defined]
    return [s["id"] for s in songs]


def test_two_users_share_files_but_not_favourites(make_user: UserFactory) -> None:
    alice, bob = make_user("alice"), make_user("bob")

    # Separate keys: each key is its own user's, and each user lists only their own keys.
    assert alice.ut_json("GET", "/me")["username"] == "alice"
    assert bob.ut_json("GET", "/me")["username"] == "bob"
    alice_keys = {k["prefix"] for k in alice.ut_json("GET", "/keys")["keys"]}
    bob_keys = {k["prefix"] for k in bob.ut_json("GET", "/keys")["keys"]}
    assert alice_keys == {alice.api_key[:12]}
    assert bob_keys == {bob.api_key[:12]}

    # Alice keeps a song: it is downloaded and archived once.
    requested = alice.ut("POST", f"/tracks/{SONG}/request", json={"reason": "keep"})
    assert requested.status_code == 202, requested.text
    track_id = alice.wait_ready(SONG)["trackId"]

    alice.rest("star", id=track_id)
    playlist = alice.rest("createPlaylist", name="Alice e2e mix", songId=track_id)["playlist"]
    assert alice.rest("getPlaylist", id=playlist["id"])["playlist"]["entry"][0]["id"] == track_id

    # Bob sees none of Alice's favourites or private playlists...
    assert starred_ids(bob.rest("getStarred2")) == []
    assert all(
        p["id"] != playlist["id"] for p in bob.rest("getPlaylists")["playlists"].get("playlist", [])
    )
    hidden = bob.rest_raw("getPlaylist", id=playlist["id"])
    assert hidden["status"] == "failed"
    assert hidden["error"]["code"] == NOT_FOUND

    # ...but the file is shared: search shows the library song, and asking for it downloads nothing.
    found = [t for t in bob.search_tracks(TITLE) if t["title"] == TITLE]
    assert [(t["id"], t["isExternal"]) for t in found] == [(track_id, False)]
    again = bob.ut("POST", f"/tracks/{SONG}/request", json={"reason": "keep"})
    assert again.status_code == 200, again.text
    assert (again.json()["trackId"], again.json()["attempts"]) == (track_id, 1)
    with alice.stream(track_id) as answer:
        alice_bytes = answer.read()
    with bob.stream(track_id) as answer:
        assert answer.status_code == 200
        assert answer.read() == alice_bytes

    # Stars are per user both ways.
    bob.rest("star", id=track_id)
    assert starred_ids(bob.rest("getStarred2")) == [track_id]
    bob.rest("unstar", id=track_id)
    assert starred_ids(bob.rest("getStarred2")) == []
    assert starred_ids(alice.rest("getStarred2")) == [track_id]

    # Revoking Bob's key locks out Bob's device only.
    bob_key_id = bob.ut_json("GET", "/keys")["keys"][0]["id"]
    assert bob.ut("DELETE", f"/keys/{bob_key_id}").status_code == 204
    assert bob.ut("GET", "/me").status_code == 401
    assert alice.ut_json("GET", "/me")["username"] == "alice"
