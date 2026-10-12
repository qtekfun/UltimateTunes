# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Api side of the canary: when it runs (daily, an admin's request, one replica only), what it
records in `canary_runs`, and that failed runs reach the notification sweep (T15)."""

import json
import time
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import anyio
import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from ultimatetunes.admin.notify import NotificationSweep, Target, save_target
from ultimatetunes.canary import web
from ultimatetunes.canary.settings import CanarySettings
from ultimatetunes.canary.store import KEY_STARTED, CanaryStore
from ultimatetunes.core.clock import FakeClock, format_ts
from ultimatetunes.core.services import Services, build_services
from ultimatetunes.db import Database
from ultimatetunes.errors import TunesError
from ultimatetunes.search.catalog import CatalogParseError
from ultimatetunes.search.fake import FakeMusicCatalog
from ultimatetunes.settings import Settings

pytestmark = pytest.mark.anyio
DAY = timedelta(hours=24)


@pytest.fixture
def services(
    settings: Settings, db: Database, clock: FakeClock, tmp_path: Path
) -> Iterator[Services]:
    configured = settings.model_copy(update={"database_path": tmp_path / "data" / "ut.db"})
    built = build_services(configured, clock)
    yield built
    built.db.close()


@pytest.fixture
def store(db: Database, clock: FakeClock) -> CanaryStore:
    return CanaryStore(db, clock)


def runs(db: Database) -> list[dict[str, Any]]:
    with db.read() as conn:
        rows = conn.execute(
            "SELECT source, worker_id, ok, message, detail FROM canary_runs ORDER BY ran_at"
        ).fetchall()
    return [dict(r) for r in rows]


def request_canary(db: Database, created_at: str, command_id: str = "c1") -> None:
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO worker_commands (id, command, created_at) VALUES (?, 'run_canary', ?)",
            (command_id, created_at),
        )


# ---------------------------------------------------------------- CanaryStore


def test_the_first_run_is_due_at_once(store: CanaryStore) -> None:
    assert store.last_started() is None
    assert store.due(DAY)
    assert store.claim(DAY)
    assert store.last_started() is not None


def test_the_next_run_is_due_a_day_later(store: CanaryStore, clock: FakeClock) -> None:
    assert store.claim(DAY)
    clock.advance(DAY.total_seconds() - 1)
    assert not store.due(DAY)
    assert not store.claim(DAY)
    clock.advance(1)
    assert store.claim(DAY)


def test_an_admin_request_makes_it_due_once(
    store: CanaryStore, db: Database, clock: FakeClock
) -> None:
    assert store.claim(DAY)
    clock.advance(60)
    request_canary(db, format_ts(clock.now()))
    clock.advance(1)
    assert store.claim(DAY)
    assert not store.claim(DAY)


def test_without_schedule_only_admin_requests_run(
    store: CanaryStore, db: Database, clock: FakeClock
) -> None:
    assert not store.claim(DAY, scheduled=False)
    request_canary(db, format_ts(clock.now()))
    assert store.claim(DAY, scheduled=False)
    clock.advance(DAY.total_seconds() * 2)
    assert not store.claim(DAY, scheduled=False)


def test_two_replicas_never_both_claim(store: CanaryStore, db: Database, clock: FakeClock) -> None:
    other = CanaryStore(db, clock)
    assert store.claim(DAY)
    clock.advance(DAY.total_seconds())
    assert [store.claim(DAY), other.claim(DAY)] == [True, False]


def test_a_replica_that_read_an_old_start_loses_the_compare_and_set(
    store: CanaryStore, db: Database, clock: FakeClock
) -> None:
    assert store.claim(DAY)
    clock.advance(DAY.total_seconds())
    original = store._due  # simulate a race between reading the start time and the update

    def due_then_moved(conn: Any, *args: Any, **kwargs: Any) -> bool:
        result = original(conn, *args, **kwargs)
        conn.execute("UPDATE settings SET value = 'moved' WHERE key = ?", (KEY_STARTED,))
        return result

    store._due = due_then_moved  # type: ignore[method-assign]
    assert not store.claim(DAY)


def test_a_replica_that_lost_the_first_insert_does_not_run(
    store: CanaryStore, db: Database, clock: FakeClock
) -> None:
    original = store._due  # simulate a race between reading the start time and the update

    def due_then_inserted(conn: Any, *args: Any, **kwargs: Any) -> bool:
        result = original(conn, *args, **kwargs)
        conn.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, 'x', 'x')", (KEY_STARTED,)
        )
        return result

    store._due = due_then_inserted  # type: ignore[method-assign]
    assert not store.claim(DAY)


# ---------------------------------------------------------------- ApiCanary


async def test_a_due_run_is_recorded(services: Services, db: Database) -> None:
    canary = web.ApiCanary(services, CanarySettings())
    report = await canary.run_once()
    assert report is not None
    assert report.ok, report.message
    [row] = runs(db)
    assert (row["source"], row["worker_id"], row["ok"], row["message"]) == ("api", None, 1, None)
    assert [c["name"] for c in json.loads(row["detail"])] == [
        "search",
        "radio",
        "album",
        "playlist",
    ]
    # Not due again until tomorrow.
    assert await canary.run_once() is None


async def test_a_failed_run_is_recorded_with_its_message(services: Services, db: Database) -> None:
    broken = FakeMusicCatalog()
    broken.fail_with = CatalogParseError("search: no shelf")
    canary = web.ApiCanary(services, CanarySettings(), catalog=lambda: broken)
    report = await canary.run_now()
    assert not report.ok
    [row] = runs(db)
    assert row["ok"] == 0
    assert row["message"].startswith("search: layout changed: search: no shelf; radio: ")


class Recorder:
    def __init__(self) -> None:
        self.sent: list[Any] = []

    async def send(self, target: Target, message: Any) -> bool:
        self.sent.append(message)
        return True


async def test_a_failed_run_reaches_the_admin_notifications(
    services: Services, db: Database, clock: FakeClock
) -> None:
    save_target(db, clock, Target("ntfy", "https://ntfy.example.net/ut-alerts"))
    clock.advance(1)
    broken = FakeMusicCatalog()
    broken.fail_with = CatalogParseError("search: no shelf")
    await web.ApiCanary(services, CanarySettings(), catalog=lambda: broken).run_now()
    clock.advance(1)
    sender = Recorder()
    await NotificationSweep(db, clock, sender).run_once()  # type: ignore[arg-type]
    [message] = sender.sent
    assert "canary" in message.body
    assert "layout changed" in message.body


def test_the_catalog_is_the_fake_on_the_test_stack(services: Services) -> None:
    assert web.canary_catalog(services) is services.catalog


def test_the_real_catalog_is_ytmusicapi_without_the_cache(services: Services) -> None:
    from ultimatetunes.search.ytmusic import YTMusicCatalog  # noqa: PLC0415

    real = Services(
        **{
            **services.__dict__,
            "settings": services.settings.model_copy(update={"fake_youtube": False}),
        }
    )
    assert isinstance(web.canary_catalog(real), YTMusicCatalog)


async def test_the_loop_survives_a_database_error(
    services: Services, monkeypatch: pytest.MonkeyPatch
) -> None:
    canary = web.ApiCanary(services, CanarySettings(canary_first_delay_s=0, canary_poll_s=0.01))
    calls: list[int] = []

    async def failing() -> None:
        calls.append(1)
        if len(calls) == 1:
            from ultimatetunes.db.driver import DatabaseError  # noqa: PLC0415

            raise DatabaseError("locked")
        raise TunesError("stop the loop")

    monkeypatch.setattr(canary, "run_once", failing)
    with pytest.raises(TunesError):
        await canary.run_forever()
    assert len(calls) == 2


def test_install_runs_the_canary_during_the_app_lifespan(services: Services, db: Database) -> None:
    app = FastAPI()
    web.install(app, services, CanarySettings(canary_first_delay_s=0, canary_poll_s=0.01))
    with TestClient(app):
        deadline = time.monotonic() + 5
        while not runs(db) and time.monotonic() < deadline:
            time.sleep(0.01)
    [row] = runs(db)
    assert row["ok"] == 1


class SlowAndBroken(FakeMusicCatalog):
    """The search hangs until released, then every call fails (a long failing run)."""

    def __init__(self) -> None:
        super().__init__()
        self.started = anyio.Event()
        self.release = anyio.Event()

    async def search_songs(self, query: str, limit: int) -> list[Any]:
        self.started.set()
        await self.release.wait()
        self.fail_with = CatalogParseError("search: no shelf")
        return await super().search_songs(query, limit)


async def test_a_long_failing_run_is_notified_even_if_a_sweep_ran_meanwhile(
    services: Services, db: Database, clock: FakeClock
) -> None:
    save_target(db, clock, Target("ntfy", "https://ntfy.example.net/ut-alerts"))
    clock.advance(1)
    catalog = SlowAndBroken()
    sender = Recorder()
    sweep = NotificationSweep(db, clock, sender)  # type: ignore[arg-type]
    canary = web.ApiCanary(services, CanarySettings(), catalog=lambda: catalog)
    async with anyio.create_task_group() as tg:
        tg.start_soon(canary.run_now)
        await catalog.started.wait()
        clock.advance(120)  # the run goes on for minutes...
        await sweep.run_once()  # ...while a sweep moves the cursor past its start
        clock.advance(120)
        catalog.release.set()
    clock.advance(1)
    await sweep.run_once()
    [message] = sender.sent
    assert "layout changed" in message.body
    [row] = runs(db)
    assert row["ok"] == 0
