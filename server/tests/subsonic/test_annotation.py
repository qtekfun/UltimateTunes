# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Stars and scrobbles: per user, keep actions on `yt:` ids, validation before writes."""

import pytest

from tests.library.harness import ANA, BOB, Harness
from tests.subsonic.test_browse import NOW, ORCHARD, pending_orchard
from ultimatetunes.errors import UpstreamUnavailable


def starred(lib: Harness, key: str = "utk_ana") -> dict[str, list[str]]:
    r = lib.rest("getStarred2", key=key)
    body = r.json()["subsonic-response"]["starred2"]
    from tests.library.harness import schema  # noqa: PLC0415

    schema("opensubsonic-subset.yaml", "GetStarred2Response").validate(r.json())
    return {
        kind: [item["id"] for item in body.get(kind, [])] for kind in ("artist", "album", "song")
    }


def jobs(lib: Harness) -> list[tuple[str, str, int]]:
    with lib.services.db.read() as conn:
        rows = conn.execute(
            "SELECT yt_video_id, state, priority FROM jobs ORDER BY created_at"
        ).fetchall()
    return [(str(r["yt_video_id"]), str(r["state"]), int(str(r["priority"]))) for r in rows]


def test_star_library_items_per_user(lib: Harness) -> None:
    ids = lib.ids()
    lib.ok(
        "star",
        "EmptyResponse",
        id=ids["Brasas"],
        albumId=ids["Harbour Lights"],
        artistId=ids["Marisol Vega"],
    )
    lib.ok("star", id=ids["Brasas"])  # starring twice is fine
    assert starred(lib) == {
        "artist": [ids["Marisol Vega"]],
        "album": [ids["Harbour Lights"]],
        "song": [ids["Brasas"]],
    }
    assert starred(lib, "utk_bob") == {"artist": [], "album": [], "song": []}
    song = lib.ok("getSong", id=ids["Brasas"])["song"]
    assert song["starred"] == NOW
    lib.ok("unstar", id=ids["Brasas"], albumId=ids["Harbour Lights"], artistId=ids["Marisol Vega"])
    assert starred(lib) == {"artist": [], "album": [], "song": []}


def test_star_accepts_album_and_artist_ids_in_id(lib: Harness) -> None:
    ids = lib.ids()
    lib.ok("star", id=[ids["Salt & Ember"], ids["The Paper Lanterns"]])
    assert starred(lib)["album"] == [ids["Salt & Ember"]]
    assert starred(lib)["artist"] == [ids["The Paper Lanterns"]]


def test_star_external_song_materializes_and_requests_it(lib: Harness) -> None:
    lib.ok("star", id="yt:Qx7Lm2pZ0aB")
    with lib.services.db.read() as conn:
        row = conn.execute(
            "SELECT t.status, t.title, t.yt_thumbnail_url FROM track_aliases a"
            " JOIN tracks t ON t.id = a.track_id WHERE a.alias = 'yt:Qx7Lm2pZ0aB'"
        ).fetchone()
    assert row is not None
    assert (row["status"], row["title"]) == ("pending", "Paper Moons (Live)")
    assert jobs(lib) == [("Qx7Lm2pZ0aB", "queued", 30)]
    assert starred(lib)["song"] == ["yt:Qx7Lm2pZ0aB"]
    # Starring again (or by another user) reuses the track and the job.
    lib.ok("star", id="yt:Qx7Lm2pZ0aB", key="utk_bob")
    assert jobs(lib) == [("Qx7Lm2pZ0aB", "queued", 30)]
    assert lib.one("SELECT COUNT(*) FROM tracks WHERE yt_video_id = 'Qx7Lm2pZ0aB'") == 1
    lib.ok("unstar", id="yt:Qx7Lm2pZ0aB")
    assert starred(lib)["song"] == []
    assert starred(lib, "utk_bob")["song"] == ["yt:Qx7Lm2pZ0aB"]


def test_star_pending_song_requests_its_job(lib: Harness) -> None:
    pending_orchard(lib)
    lib.ok("star", id="yt:Rb8Tn3ZcYv0")
    assert jobs(lib) == [("Rb8Tn3ZcYv0", "queued", 30)]
    assert starred(lib)["song"] == ["yt:Rb8Tn3ZcYv0"]
    assert lib.one("SELECT track_id FROM starred_tracks") == ORCHARD


def test_unstar_never_materializes(lib: Harness) -> None:
    lib.ok("unstar", id="yt:Qx7Lm2pZ0aB")
    assert lib.one("SELECT COUNT(*) FROM tracks WHERE status = 'pending'") == 0
    assert lib.catalog.calls == []


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"id": "ytalbum:MPREb_k3Vd9QmT2xL"}, 0),
        ({"albumId": "ytalbum:MPREb_k3Vd9QmT2xL"}, 0),
        ({"artistId": "ytartist:UCq8XbV1r0LwZ5mN3tYp7kQe"}, 0),
        ({"id": "0199d6a2-4c1e-7b3a-9f10-2a6c8e01ffff"}, 70),
        ({"albumId": "0199d6a2-4c1e-7b3a-9f10-2a6c8e01ffff"}, 70),
        ({"artistId": "0199d6a2-4c1e-7b3a-9f10-2a6c8e01ffff"}, 70),
        ({"id": "yt:AAAAAAAAAAA"}, 70),
        ({"id": "nope"}, 70),
    ],
)
def test_star_errors_write_nothing(lib: Harness, params: dict[str, str], expected: int) -> None:
    brasas = lib.ids()["Brasas"]
    ids = [brasas, *([params["id"]] if "id" in params else [])]
    assert lib.error("star", **{**params, "id": ids}) == expected
    assert starred(lib)["song"] == []
    if expected == 0 or "yt:" not in params.get("id", ""):
        assert lib.error("unstar", **{**params, "id": ids}) == expected


def test_too_many_ids(lib: Harness) -> None:
    assert lib.error("star", id=[lib.ids()["Brasas"]] * 1001) == 0


def test_star_when_the_catalog_is_down(lib: Harness) -> None:
    lib.catalog.fail_with = UpstreamUnavailable()
    assert lib.error("star", id=["yt:Qx7Lm2pZ0aB", lib.ids()["Brasas"]]) == 0
    assert starred(lib)["song"] == []


def stats(lib: Harness, user: str, track: str) -> tuple[int, str] | None:
    with lib.services.db.read() as conn:
        row = conn.execute(
            "SELECT play_count, last_played_at FROM user_track_stats"
            " WHERE user_id = ? AND track_id = ?",
            (user, track),
        ).fetchone()
    return None if row is None else (int(str(row["play_count"])), str(row["last_played_at"]))


def test_scrobble(lib: Harness) -> None:
    song = lib.ids()["Brasas"]
    lib.ok("scrobble", "EmptyResponse", id=song, time="1760256000000", c="UltimateTunes-Android")
    lib.ok("scrobble", id=song, time="1760250000000")
    assert stats(lib, ANA.user_id, song) == (2, "2025-10-12T08:00:00.000Z")
    assert stats(lib, BOB.user_id, song) is None
    body = lib.ok("getSong", id=song)["song"]
    assert body["playCount"] == 2
    assert body["played"] == "2025-10-12T08:00:00.000Z"
    # Without time: now. A time in the future counts as now.
    lib.ok("scrobble", id=song)
    lib.ok("scrobble", id=song, time="99999999999999")
    assert stats(lib, ANA.user_id, song) == (4, NOW)
    clients = lib.one("SELECT COUNT(*) FROM play_history WHERE client = 'UltimateTunes-Android'")
    assert clients == 1


def test_now_playing_counts_nothing(lib: Harness) -> None:
    song = lib.ids()["Brasas"]
    lib.ok("scrobble", id=[song, "yt:Qx7Lm2pZ0aB"], submission="false")
    assert stats(lib, ANA.user_id, song) is None
    assert lib.one("SELECT COUNT(*) FROM play_history WHERE submission = 0") == 1
    assert lib.one("SELECT COUNT(*) FROM tracks WHERE status = 'pending'") == 0


def test_scrobble_external_song_materializes_it(lib: Harness) -> None:
    lib.ok("scrobble", id="yt:Qx7Lm2pZ0aB", submission="true")
    assert jobs(lib) == [("Qx7Lm2pZ0aB", "queued", 30)]
    assert lib.one("SELECT COUNT(*) FROM play_history WHERE submission = 1") == 1


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({}, 10),
        ({"id": ""}, 10),
        ({"id": "SONG", "time": ["1", "2"]}, 0),
        ({"id": "SONG", "time": "x"}, 0),
        ({"id": "SONG", "submission": "maybe"}, 0),
        ({"id": "ytalbum:MPREb_k3Vd9QmT2xL"}, 70),
    ],
)
def test_scrobble_errors(lib: Harness, params: dict[str, object], expected: int) -> None:
    resolved = {k: (lib.ids()["Brasas"] if v == "SONG" else v) for k, v in params.items()}
    assert lib.error("scrobble", **resolved) == expected
    assert lib.one("SELECT COUNT(*) FROM play_history") == 0


def test_xml(lib: Harness) -> None:
    ids = lib.ids()
    star = lib.rest("star", fmt="xml", id=ids["Brasas"], albumId=ids["Harbour Lights"])
    assert star.headers["content-type"] == "application/xml; charset=utf-8"
    assert 'status="ok"' in star.text
    lib.ok("star", id="yt:Qx7Lm2pZ0aB")
    scrobble = lib.rest("scrobble", fmt="xml", id=ids["Brasas"], time="1000")
    assert 'status="ok"' in scrobble.text
    xml = lib.rest("getStarred2", fmt="xml").text
    assert "<starred2>" in xml
    assert xml.count("<song ") == 2
    assert f'<song id="{ids["Brasas"]}"' in xml
    assert '<song id="yt:Qx7Lm2pZ0aB"' in xml
    assert f'<album id="{ids["Harbour Lights"]}"' in xml
    assert "<replayGain/>" in xml
    assert 'playCount="1"' in xml
    assert lib.rest("star", fmt="xml", id="nope").text.count('<error code="70"') == 1
