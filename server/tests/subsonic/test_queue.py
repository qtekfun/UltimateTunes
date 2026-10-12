# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The saved play queue: raw ids, never a download, resolved when read."""

import pytest

from tests.library.harness import Harness
from tests.subsonic.test_browse import ORCHARD, archive_low_tide, pending_orchard
from ultimatetunes.errors import UpstreamUnavailable


def test_no_saved_queue(lib: Harness) -> None:
    body = lib.ok("getPlayQueue", "GetPlayQueueResponse")
    assert "playQueue" not in body


def test_save_and_read(lib: Harness) -> None:
    ids = lib.ids()
    pending_orchard(lib)
    tidewater = archive_low_tide(lib)
    lib.ok(
        "savePlayQueue",
        "EmptyResponse",
        id=[ids["Brasas"].upper(), "yt:Qx7Lm2pZ0aB", "yt:Rb8Tn3ZcYv0", "yt:Fk2Lp9QwXa1"],
        current="yt:Fk2Lp9QwXa1",
        position="73500",
        c="UltimateTunes-Android",
    )
    # Saving never materializes or requests anything.
    assert lib.one("SELECT COUNT(*) FROM jobs") == 0
    assert lib.one("SELECT COUNT(*) FROM track_aliases WHERE alias = 'yt:Qx7Lm2pZ0aB'") == 0
    stored = lib.one("SELECT item_id FROM play_queue_entries WHERE idx = 0")
    assert stored == ids["Brasas"]
    queue = lib.ok("getPlayQueue", "GetPlayQueueResponse")["playQueue"]
    assert queue["username"] == "ana"
    assert queue["changedBy"] == "UltimateTunes-Android"
    assert queue["position"] == 73500
    assert queue["current"] == tidewater
    assert [e["id"] for e in queue["entry"]] == [
        ids["Brasas"],
        "yt:Qx7Lm2pZ0aB",
        "yt:Rb8Tn3ZcYv0",
        tidewater,
    ]
    assert queue["entry"][1]["title"] == "Paper Moons (Live)"
    assert lib.one("SELECT track_id FROM track_aliases WHERE alias = 'yt:Rb8Tn3ZcYv0'") == ORCHARD
    assert "playQueue" not in lib.ok("getPlayQueue", key="utk_bob")
    xml = lib.rest("getPlayQueue", fmt="xml").text
    assert xml.count("<entry ") == 4


def test_unknown_items_when_reading(lib: Harness) -> None:
    gone = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01ffff"
    lib.ok("savePlayQueue", id=[gone, "yt:Qx7Lm2pZ0aB", "yt:AAAAAAAAAAA"], current=gone)
    queue = lib.ok("getPlayQueue", "GetPlayQueueResponse")["playQueue"]
    # A library id that no longer exists is left out; `current` stays as saved.
    assert queue["current"] == gone
    assert [e["id"] for e in queue["entry"]] == ["yt:Qx7Lm2pZ0aB", "yt:AAAAAAAAAAA"]
    placeholder = queue["entry"][1]
    assert placeholder["title"] == "yt:AAAAAAAAAAA"
    lib.catalog.fail_with = UpstreamUnavailable()
    queue = lib.ok("getPlayQueue", "GetPlayQueueResponse")["playQueue"]
    assert [e["title"] for e in queue["entry"]] == ["yt:Qx7Lm2pZ0aB", "yt:AAAAAAAAAAA"]


def test_saving_nothing_clears_the_queue(lib: Harness) -> None:
    lib.ok("savePlayQueue", id=lib.ids()["Brasas"])
    lib.ok("savePlayQueue")
    assert "playQueue" not in lib.ok("getPlayQueue")
    assert lib.one("SELECT COUNT(*) FROM play_queue_entries") == 0


@pytest.mark.parametrize(
    "params",
    [
        {"id": "ytalbum:MPREb_k3Vd9QmT2xL"},
        {"id": "nope"},
        {"id": "yt:Qx7Lm2pZ0aB", "current": "nope"},
    ],
)
def test_invalid_ids_are_refused(lib: Harness, params: dict[str, str]) -> None:
    assert lib.error("savePlayQueue", **params) == 70


def test_invalid_numbers(lib: Harness) -> None:
    assert lib.error("savePlayQueue", id="yt:Qx7Lm2pZ0aB", position="-1") == 0
    assert lib.error("savePlayQueue", id="yt:Qx7Lm2pZ0aB", position="x") == 0
    assert lib.error("savePlayQueue", id=["yt:Qx7Lm2pZ0aB"] * 1001) == 0
