# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Podcast progress: newest wins, per user, incremental sync and "continue listening"."""

import base64
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import CONTRACTS
from ultimatetunes.app import create_app
from ultimatetunes.core.authn import Principal
from ultimatetunes.core.clock import FakeClock, format_ts
from ultimatetunes.core.services import Services, build_services
from ultimatetunes.db import migrate
from ultimatetunes.settings import Settings

ANA = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01e001"
BEN = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01e002"
SHOW = "0199d6a2-4c1e-7b3a-9f10-2a6c8e015001"
ONE = "0199d6a2-4c1e-7b3a-9f10-2a6c8e016001"
TWO = "0199d6a2-4c1e-7b3a-9f10-2a6c8e016002"
VIDEO = {ONE: "Pd4Kx9Lm2Qa", TWO: "Pd4Kx9Lm2Qb"}


class Callers:
    """The key is the user id."""

    def authenticate_api_key(
        self, header_key: str | None, query_key: str | None, client_ip: str | None
    ) -> Principal:
        return Principal(str(header_key), "someone", "user")

    def authenticate_subsonic(self, params: object, client_ip: str | None) -> Principal:
        raise AssertionError


def _seed(services: Services) -> None:
    at = format_ts(services.clock.now())
    with services.db.transaction() as conn:
        for user, name in ((ANA, "ana"), (BEN, "ben")):
            conn.execute(
                "INSERT INTO users (id, username, password_hash, role, created_at, updated_at) "
                "VALUES (?, ?, 'x', 'user', ?, ?)",
                (user, name, at, at),
            )
        conn.execute(
            "INSERT INTO podcast_shows (id, source, title, created_at, updated_at) "
            "VALUES (?, 'youtube', 'Tide Tables', ?, ?)",
            (SHOW, at, at),
        )
        for seq, (episode, video) in enumerate(VIDEO.items()):
            conn.execute(
                "INSERT INTO podcast_episodes (id, show_id, yt_video_id, title, list_seq, "
                "state, discovered_at, updated_at) VALUES (?, ?, ?, 'Slack water', ?, "
                "'remote', ?, ?)",
                (episode, SHOW, video, seq, at, at),
            )


@pytest.fixture
def api(settings: Settings, clock: FakeClock) -> Iterator[TestClient]:
    configured = settings.model_copy(update={"migrations_dir": CONTRACTS / "db" / "migrations"})
    conn = migrate.connect(configured.database_file)
    migrate.migrate(conn, configured.migrations_dir, clock)
    conn.close()
    services = build_services(configured, clock)
    services.authenticator = Callers()
    with TestClient(create_app(services=services)) as client:
        _seed(services)
        yield client


def at(clock: FakeClock, seconds: int = 0) -> str:
    return format_ts(clock.now() + timedelta(seconds=seconds))


def update(episode: str, position: int, changed: str, **extra: object) -> dict[str, object]:
    return {
        "episodeId": episode,
        "positionMs": position,
        "played": False,
        "changedAt": changed,
        **extra,
    }


def stored(episode: str, position: int, changed: str, *, keep: bool = False) -> dict[str, object]:
    return {**update(episode, position, changed), "keep": keep}


def put(api: TestClient, *items: dict[str, object], user: str = ANA) -> dict[str, Any]:
    r = api.put("/ut/v1/podcasts/progress", json={"items": items}, headers={"X-Api-Key": user})
    assert r.status_code == 200, r.text
    return dict(r.json())


def get(api: TestClient, path: str = "progress", user: str = ANA, **params: Any) -> dict[str, Any]:
    r = api.get(f"/ut/v1/podcasts/{path}", params=params, headers={"X-Api-Key": user})
    assert r.status_code == 200, r.text
    return dict(r.json())


def test_an_older_update_arriving_later_changes_nothing(api: TestClient, clock: FakeClock) -> None:
    newer = put(api, update(ONE, 900, at(clock, -10), keep=True))["items"]
    older = put(api, update(ONE, 100, at(clock, -60), played=True, keep=False))["items"]
    assert older == newer == [stored(ONE, 900, at(clock, -10), keep=True)]
    assert get(api)["items"] == newer


def test_out_of_order_inside_a_batch(api: TestClient, clock: FakeClock) -> None:
    result = put(
        api,
        update(ONE, 500, at(clock, -10)),
        update(ONE, 100, at(clock, -30)),
        update(TWO, 100, at(clock, -30)),
        update(TWO, 500, at(clock, -10)),
    )
    assert [(i["episodeId"], i["positionMs"]) for i in result["items"]] == [(ONE, 500), (TWO, 500)]


def test_times_are_compared_as_instants(api: TestClient) -> None:
    put(api, update(ONE, 500, "2026-10-12T07:00:00Z"))
    # 06:30 UTC, written with an offset that makes its text look later.
    result = put(api, update(ONE, 100, "2026-10-12T09:30:00+03:00"))
    assert result["items"][0]["positionMs"] == 500


def test_the_same_time_lets_the_later_arrival_win(api: TestClient, clock: FakeClock) -> None:
    moment = at(clock, -10)
    put(api, update(ONE, 500, moment))
    assert put(api, update(ONE, 600, moment))["items"][0]["positionMs"] == 600


def test_a_future_time_counts_as_now(api: TestClient, clock: FakeClock) -> None:
    held = put(api, update(ONE, 500, "9999-12-31T23:59:59-12:00"))["items"][0]
    assert held["changedAt"] == at(clock)
    clock.advance(5)
    assert put(api, update(ONE, 700, at(clock)))["items"][0]["positionMs"] == 700


def test_an_ancient_time_is_kept_in_range(api: TestClient) -> None:
    held = put(api, update(ONE, 5, "0001-01-01T00:00:00+12:00"))["items"][0]
    assert held["changedAt"] == "1970-01-01T00:00:00.000Z"


def test_an_omitted_keep_is_unchanged(api: TestClient, clock: FakeClock) -> None:
    assert put(api, update(TWO, 1, at(clock, -90)))["items"][0]["keep"] is False
    put(api, update(ONE, 1, at(clock, -30), keep=True))
    assert put(api, update(ONE, 2, at(clock, -20)))["items"][0]["keep"] is True
    assert put(api, update(ONE, 2, at(clock, -10), keep=False))["items"][0]["keep"] is False


def test_youtube_ids_resolve_and_unknown_ids_are_listed(api: TestClient, clock: FakeClock) -> None:
    unknown = [
        "ytepisode:AAAAAAAAAAA",
        "ytepisode:bad",
        "0199d6a2-4c1e-7b3a-9f10-2a6c8e019999",
        "nonsense",
    ]
    result = put(
        api,
        update(f"ytepisode:{VIDEO[ONE]}", 10, at(clock)),
        update(TWO.upper(), 20, at(clock)),
        *(update(raw, 1, at(clock)) for raw in [*unknown, unknown[0]]),
    )
    assert [i["episodeId"] for i in result["items"]] == [ONE, TWO]
    assert result["unknown"] == unknown


def test_progress_is_per_user(api: TestClient, clock: FakeClock) -> None:
    put(api, update(ONE, 500, at(clock, -10), keep=True))
    assert get(api, user=BEN)["items"] == []
    assert get(api, "continue", user=BEN)["episodes"] == []
    put(api, update(ONE, 7, at(clock, -60)), user=BEN)
    assert get(api, user=BEN)["items"] == [stored(ONE, 7, at(clock, -60))]
    assert get(api)["items"] == [stored(ONE, 500, at(clock, -10), keep=True)]


def test_sync_pages_since(api: TestClient, clock: FakeClock) -> None:
    put(api, update(ONE, 1, at(clock)))
    clock.advance(120)
    second = at(clock)
    put(api, update(TWO, 2, second))

    first = get(api, limit=1)
    assert [i["episodeId"] for i in first["items"]] == [ONE]
    assert first["syncedAt"] == at(clock, -60)
    last = get(api, limit=1, cursor=first["nextCursor"])
    assert [i["episodeId"] for i in last["items"]] == [TWO]
    assert last["nextCursor"] is None
    assert [i["episodeId"] for i in get(api, since=second)["items"]] == [TWO]
    assert get(api, since="9999-12-31T23:59:59-12:00")["items"] == []


def test_sync_pages_rows_stored_at_the_same_time(api: TestClient, clock: FakeClock) -> None:
    put(api, update(TWO, 1, at(clock)), update(ONE, 1, at(clock)))
    first = get(api, limit=1)
    rest = get(api, limit=1, cursor=first["nextCursor"])
    assert [first["items"][0]["episodeId"], rest["items"][0]["episodeId"]] == [ONE, TWO]


def test_an_older_change_stored_late_is_synced_a_repeat_is_not(
    api: TestClient, clock: FakeClock
) -> None:
    clock.advance(600)
    offline = update(ONE, 5, at(clock, -300))
    put(api, offline)
    assert get(api, since=at(clock))["items"][0]["positionMs"] == 5
    clock.advance(600)
    put(api, offline)
    assert get(api, since=at(clock))["items"] == []


def _cursor(text: bytes) -> str:
    return base64.urlsafe_b64encode(text).decode()


@pytest.mark.parametrize(
    "cursor",
    [
        "!!!",
        "////",
        _cursor(b"nope"),
        _cursor(b"x y"),
        _cursor(b"2026-10-12T08:00:00.000Z nope"),
    ],
)
def test_a_bad_cursor_is_refused(api: TestClient, cursor: str) -> None:
    r = api.get("/ut/v1/podcasts/progress", params={"cursor": cursor}, headers={"X-Api-Key": ANA})
    assert (r.status_code, r.json()["code"]) == (400, "invalid_parameter")


GOOD = {"episodeId": ONE, "positionMs": 1, "played": False, "changedAt": "2026-10-12T08:00:00Z"}


@pytest.mark.parametrize(
    "body",
    [
        None,
        {"items": []},
        {"items": [GOOD] * 201},
        {"items": [GOOD], "extra": 1},
        {"items": [{**GOOD, "extra": 1}]},
        {"items": [{**GOOD, "positionMs": -1}]},
        {"items": [{**GOOD, "positionMs": 86_400_001}]},
        {"items": [{**GOOD, "positionMs": "1"}]},
        {"items": [{**GOOD, "played": 1}]},
        {"items": [{**GOOD, "keep": None}]},
        {"items": [{**GOOD, "changedAt": "2026-10-12T08:00:00"}]},
        {"items": [{**GOOD, "changedAt": 1}]},
        {"items": [{**GOOD, "episodeId": ""}]},
    ],
)
def test_invalid_batches_store_nothing(api: TestClient, body: object) -> None:
    r = api.put("/ut/v1/podcasts/progress", json=body, headers={"X-Api-Key": ANA})
    assert (r.status_code, r.json()["code"]) == (400, "invalid_parameter")
    assert get(api)["items"] == []


def test_continue_lists_started_episodes(api: TestClient, clock: FakeClock) -> None:
    added = at(clock)
    put(api, update(TWO, 10, at(clock, -60)), update(ONE, 20, at(clock, -10), keep=True))
    episodes = get(api, "continue")["episodes"]
    assert [e["id"] for e in episodes] == [ONE, TWO]
    assert episodes[0] == {
        "id": ONE,
        "showId": SHOW,
        "showTitle": "Tide Tables",
        "title": "Slack water",
        "coverArt": f"pe-{ONE}",
        "publishedAt": None,
        "durationMs": None,
        "addedAt": added,
        "state": "remote",
        "sizeBytes": None,
        "progress": stored(ONE, 20, at(clock, -10), keep=True),
    }
    assert [e["id"] for e in get(api, "continue", limit=1)["episodes"]] == [ONE]
    put(api, update(ONE, 20, at(clock), played=True), update(TWO, 0, at(clock)))
    assert get(api, "continue")["episodes"] == []
