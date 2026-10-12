# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`ImportRunner` failure paths and resumes, run directly (no HTTP)."""

from dataclasses import replace
from typing import Any

import pytest

from tests.imports.conftest import USER, FixtureCatalog
from ultimatetunes.core.clock import FakeClock, format_ts
from ultimatetunes.core.services import Services
from ultimatetunes.errors import UpstreamUnavailable
from ultimatetunes.ids.uuid7 import new_id
from ultimatetunes.imports import render
from ultimatetunes.imports.files import SourceItem
from ultimatetunes.imports.repository import ImportRepository, ImportRow, TrackRow
from ultimatetunes.imports.runner import ImportRunner
from ultimatetunes.search.fake import PLAYLIST_ID

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def new_import(
    services: Services,
    *,
    source: str = "csv",
    playlist_id: str | None = None,
    items: tuple[SourceItem, ...] = (),
    state: str = "queued",
) -> str:
    import_id = new_id(services.clock)
    now = format_ts(services.clock.now())
    with services.db.transaction() as conn:
        repo = ImportRepository(conn)
        repo.create(
            import_id=import_id,
            user_id=USER,
            source=source,  # type: ignore[arg-type]
            source_url=None,
            source_playlist_id=playlist_id,
            name=None,
            now=now,
        )
        repo.add_items(import_id, items, now)
        repo.set_state(import_id, state, now)  # type: ignore[arg-type]
    return import_id


def load(services: Services, import_id: str) -> ImportRow:
    with services.db.read() as conn:
        row = ImportRepository(conn).get(import_id)
    assert row is not None
    return row


def report(services: Services, import_id: str) -> dict[str, Any]:
    with services.db.read() as conn:
        repo = ImportRepository(conn)
        row = repo.get(import_id)
        assert row is not None
        items = repo.items(import_id)
        return render.full(row, items, repo.tracks([i.track_id for i in items if i.track_id]))


async def test_an_unreadable_playlist_fails_the_import(services: Services) -> None:
    runner = ImportRunner.of(services)
    missing = new_import(services, source="ytmusic", playlist_id="PLnope")
    await runner.run(missing)
    body = report(services, missing)
    assert body["state"] == "failed"
    assert body["error"]["code"] == "not_found"
    assert "private" in body["error"]["message"]
    assert body["finishedAt"] is not None

    services.catalog.fail_with = UpstreamUnavailable("down")  # type: ignore[attr-defined]
    down = new_import(services, source="ytmusic", playlist_id=PLAYLIST_ID)
    await runner.run(down)
    assert report(services, down)["error"] == {"code": "upstream_unavailable", "message": "down"}
    # A finished import is left alone.
    await runner.run(down)
    assert load(services, down).state == "failed"
    await runner.run("0199d6a2-4c1e-7b3a-9f10-000000000000")


async def test_catalog_failures_fail_items_not_the_import(
    services: Services, catalog: FixtureCatalog
) -> None:
    catalog.fail_with = UpstreamUnavailable("throttled")
    import_id = new_import(services, items=(SourceItem("Paper Canyon", ("Marisol Vega",)),))
    await ImportRunner.of(services).run(import_id)
    body = report(services, import_id)
    assert body["state"] == "done"
    assert body["items"][0]["state"] == "failed"
    assert body["items"][0]["error"] == "throttled"
    assert body["progress"] == 1
    assert body["playlistId"] is not None


async def test_an_unexpected_error_ends_the_import(
    services: Services, catalog: FixtureCatalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(query: str, limit: int) -> list[Any]:
        raise RuntimeError("bug")

    monkeypatch.setattr(catalog, "search_songs", boom)
    import_id = new_import(services, items=(SourceItem("Paper Canyon", ("Marisol Vega",)),))
    await ImportRunner.of(services).run(import_id)
    row = load(services, import_id)
    assert (row.state, row.error_code, row.error_message) == (
        "failed",
        "internal_error",
        "Internal error",
    )


async def test_a_youtube_import_resumes_from_its_items(
    services: Services, catalog: FixtureCatalog
) -> None:
    items = (
        SourceItem("Night Ferry", ("The Paper Lanterns",), video_id="Wq5Jd7HsKe2"),
        SourceItem("Gone", ("Nobody",), video_id="Zz9Zz9Zz9Zz"),
    )
    import_id = new_import(
        services, source="ytmusic", playlist_id=PLAYLIST_ID, items=items, state="matching"
    )
    await ImportRunner.of(services).run(import_id)
    body = report(services, import_id)
    assert [i["state"] for i in body["items"]] == ["matched", "not_found"]
    assert catalog.calls.count("track") == 2
    assert "playlist" not in catalog.calls


async def test_merged_tracks_show_as_the_track_they_joined(
    services: Services, clock: FakeClock
) -> None:
    import_id = new_import(services, items=(SourceItem("Paper Canyon", ("Marisol Vega",)),))
    await ImportRunner.of(services).run(import_id)
    pending = report(services, import_id)["items"][0]["track"]
    target = new_id(clock)
    now = format_ts(clock.now())
    with services.db.transaction() as conn:
        conn.execute(
            "INSERT INTO tracks (id, status, title, title_norm, artist_name, album_name,"
            " duration_ms, year, created_at, updated_at)"
            " VALUES (?, 'ready', 'Paper Canyon', 'paper canyon', 'Marisol Vega', NULL,"
            " 209000, 2024, ?, ?)",
            (target, now, now),
        )
        conn.execute(
            "UPDATE tracks SET status = 'merged', merged_into = ? WHERE id <> ?", (target, target)
        )
    merged = report(services, import_id)["items"][0]["track"]
    assert pending["id"].startswith("yt:")
    assert (merged["id"], merged["libraryState"], merged["durationSec"]) == (target, "ready", 209)
    with services.db.transaction() as conn:
        conn.execute("UPDATE tracks SET merged_into = NULL WHERE id <> ?", (target,))
    assert report(services, import_id)["items"][0]["track"] is None


async def test_progress_counts_decided_items(services: Services) -> None:
    items = (SourceItem("a"), SourceItem("b"))
    import_id = new_import(services, items=items, state="matching")
    now = format_ts(services.clock.now())
    with services.db.transaction() as conn:
        ImportRepository(conn).record_item(import_id, 0, state="not_found", now=now)
    row = load(services, import_id)
    assert render.progress(row) == 0.5
    assert render.summary(row)["notFound"] == 1
    empty = new_import(services)
    assert render.progress(load(services, empty)) == 0.0


def test_library_tracks_render_with_their_covers() -> None:
    track = TrackRow(
        id="t",
        status="ready",
        title="Night Ferry",
        artist_name="The Paper Lanterns",
        artist_id="ar1",
        album_name="Lanterns at Dusk",
        album_id="al1",
        duration_ms=241_400,
        year=2024,
        yt_video_id="Wq5Jd7HsKe2",
        yt_album_browse_id=None,
        yt_artist_channel_id=None,
        merged_into=None,
    )
    assert render.track_item(track)["coverArt"] == "al-al1"
    no_album = render.track_item(replace(track, album_id=None))
    assert (no_album["coverArt"], no_album["durationSec"]) == ("ar-ar1", 241)


async def test_finish_runs_once(services: Services) -> None:
    import_id = new_import(services, items=(SourceItem("x"),))
    now = format_ts(services.clock.now())
    with services.db.transaction() as conn:
        ImportRepository(conn).finish(import_id, new_id(services.clock), now)
        ImportRepository(conn).finish(import_id, new_id(services.clock), now)
        ImportRepository(conn).finish("0199d6a2-4c1e-7b3a-9f10-000000000000", "x", now)
    with services.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM playlists").scalar() == 1


async def test_searches_are_paced(services: Services, monkeypatch: pytest.MonkeyPatch) -> None:
    pauses: list[float] = []

    async def sleep(seconds: float) -> None:
        pauses.append(seconds)

    monkeypatch.setattr("ultimatetunes.imports.runner.anyio.sleep", sleep)
    monkeypatch.setenv("UT_IMPORT_SEARCH_INTERVAL_S", "0.5")
    items = (SourceItem("Paper Canyon (Live)", ("Marisol Vega",)), SourceItem("x", ("y",)))
    import_id = new_import(services, items=items)
    await ImportRunner.of(services).run(import_id)
    assert pauses == [0.5, 0.5, 0.5]
