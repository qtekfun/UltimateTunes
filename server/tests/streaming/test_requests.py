# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""What a streaming request does besides sending bytes: HEAD, listener caps, clients that go
away, songs archived meanwhile, pending tracks, unknown ids, and `/ut/v1/server`."""

from dataclasses import replace

import anyio
import httpx
import pytest
from starlette.requests import Request

from tests.streaming.harness import ANA, AUDIO, OTHER_VIDEO, VIDEO, Listening, Live, serve, until
from tests.streaming.test_stream import envelope_code, requested, start
from ultimatetunes.core.clock import FakeClock, format_ts
from ultimatetunes.errors import InvalidParameter, NotFound, StreamFailed
from ultimatetunes.ids.resolve import TrackRef
from ultimatetunes.ids.virtual import VirtualId
from ultimatetunes.jobs.queue import PRIORITY_KEEP, PRIORITY_STREAM
from ultimatetunes.search.fake import FakeMusicCatalog
from ultimatetunes.settings import Settings
from ultimatetunes.streaming import service
from ultimatetunes.streaming.service import StreamingWhileDownloading
from ultimatetunes.subsonic.router import SubsonicRequest

pytestmark = pytest.mark.anyio
TRACK = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01c0aa"


def add_pending(live: Live, track_id: str = TRACK, video: str | None = VIDEO) -> None:
    now = format_ts(live.clock.now())
    with live.services.db.transaction() as conn:
        conn.execute(
            "INSERT INTO tracks (id, status, title, title_norm, artist_name, yt_video_id,"
            " created_at, updated_at) VALUES (?, 'pending', 'P', 'p', 'A', ?, ?, ?)",
            (track_id, video, now, now),
        )


def archive(live: Live, track_id: str, job_id: str | None) -> None:
    """What `complete` leaves behind: the file in /music, the track ready, the job ready."""
    path = "The Paper Lanterns/Glass Orchard.opus"
    target = live.services.settings.music_dir / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"archived" * 10)
    now = format_ts(live.clock.now())
    with live.services.db.transaction() as conn:
        conn.execute(
            "UPDATE tracks SET status = 'ready', path = ?, format = 'opus', size_bytes = 80,"
            " archived_at = ? WHERE id = ?",
            (path, now, track_id),
        )
        if job_id is not None:
            conn.execute(
                "UPDATE jobs SET state = 'ready', lease_id = NULL, lease_expires_at = NULL"
                " WHERE id = ?",
                (job_id,),
            )


# ------------------------------------------------------------------ HEAD


async def test_head_never_requests_a_download(live: Live) -> None:
    r = await live.client.head("/rest/stream", params=live.params(live.song()))
    assert r.status_code == 200
    assert r.headers["accept-ranges"] == "none"
    assert r.headers["cache-control"] == "no-store"
    assert "content-length" not in r.headers
    assert live.one("SELECT COUNT(*) FROM tracks") == 0
    assert live.one("SELECT COUNT(*) FROM jobs") == 0
    # A pending track (starred, say) is not requested by a HEAD either.
    add_pending(live)
    r = await live.client.head("/rest/download", params=live.params(TRACK))
    assert r.status_code == 200
    assert live.one("SELECT COUNT(*) FROM jobs") == 0


async def test_head_never_requests_a_download_on_any_spelling(live: Live) -> None:
    """Audit I6: `.view` suffixes and `download` too; a HEAD only ever reads."""
    add_pending(live)
    for path in ("/rest/stream.view", "/rest/download.view", "/rest/stream", "/rest/download"):
        for song in (TRACK, live.song()):
            r = await live.client.head(path, params=live.params(song))
            assert r.status_code == 200
            assert r.content == b""
    assert live.one("SELECT COUNT(*) FROM jobs") == 0
    assert live.one("SELECT COUNT(*) FROM tracks") == 1


async def test_head_of_a_running_download_has_its_headers(live: Live) -> None:
    async with anyio.create_task_group() as group:
        listening = start(live, group)
        dl = await requested(live)
        r = await live.client.head("/rest/stream", params=live.params(live.song()))
        assert r.status_code == 200
        assert "content-length" not in r.headers  # no report yet
        dl.write(100)
        r = await live.client.head("/rest/stream", params=live.params(live.song()))
        assert r.status_code == 200
        assert r.headers["content-length"] == str(len(AUDIO))
        assert r.headers["accept-ranges"] == "bytes"
        assert r.headers["content-type"] == "audio/webm"
        assert r.content == b""
        ranged = await live.client.head(
            "/rest/download",
            params=live.params(live.song()),
            headers={"Range": "bytes=10-19"},
        )
        assert ranged.status_code == 206
        assert ranged.headers["content-range"] == f"bytes 10-19/{len(AUDIO)}"
        assert ranged.headers["content-length"] == "10"
        assert "attachment" in ranged.headers["content-disposition"]
        past = await live.client.head(
            "/rest/stream", params=live.params(live.song()), headers={"Range": "bytes=9999-"}
        )
        assert past.status_code == 416
        # A HEAD is not a listener.
        assert live.listeners(dl.job_id) == 1
        dl.finish()
        await listening.done.wait()


async def test_head_of_a_failed_download_is_error_70(live: Live) -> None:
    async with anyio.create_task_group() as group:
        listening = start(live, group)
        dl = await requested(live)
        dl.fail()
        await listening.done.wait()
    # The track is failed now: the library answers before the seam (T05).
    r = await live.client.head("/rest/stream", params=live.params(live.song()))
    assert r.status_code == 404
    # A job failed while its track stayed pending (a race) answers the same from here.
    with live.services.db.transaction() as conn:
        conn.execute("UPDATE tracks SET status = 'pending'")
    r = await live.client.head("/rest/stream", params=live.params(live.song()))
    assert r.status_code == 404


def direct(live: Live, raw: str, method: str = "GET") -> SubsonicRequest:
    """A request as the media route hands it to the seam (for races a client cannot cause)."""
    scope = {
        "type": "http",
        "method": method,
        "path": "/rest/stream",
        "headers": [],
        "query_string": b"",
    }
    return SubsonicRequest(Request(scope), {"id": [raw]}, "json", live.services, ANA)


def streams(live: Live) -> StreamingWhileDownloading:
    found = live.client_app.state.pending_streams
    assert isinstance(found, StreamingWhileDownloading)
    return found


async def test_a_job_archived_under_a_head_answers_from_the_library(live: Live) -> None:
    add_pending(live)
    job = live.services.jobs.enqueue(track_id=TRACK, video_id=VIDEO, priority=PRIORITY_KEEP)
    archive(live, TRACK, job.id)
    target = TrackRef(TRACK, "pending")  # what the media route saw a moment before
    r = await streams(live).serve(
        direct(live, TRACK, "HEAD"), target, video=VIDEO, download=False, head=True
    )
    assert r.status_code == 200
    assert r.headers["content-length"] == "80"


async def test_an_external_song_archived_meanwhile_answers_from_the_library(live: Live) -> None:
    add_pending(live)
    archive(live, TRACK, None)
    target = VirtualId("song", VIDEO)  # resolved before the archive finished
    r = await streams(live).serve(
        direct(live, f"yt:{VIDEO}"), target, video=VIDEO, download=False, head=False
    )
    assert r.status_code == 200
    assert r.headers["content-length"] == "80"
    assert live.one("SELECT COUNT(*) FROM jobs") == 0


async def test_a_track_that_failed_meanwhile_is_error_70(live: Live) -> None:
    add_pending(live)
    with live.services.db.transaction() as conn:
        conn.execute("UPDATE tracks SET status = 'failed'")
    with pytest.raises(StreamFailed):
        await streams(live).serve(
            direct(live, f"yt:{VIDEO}"),
            VirtualId("song", VIDEO),
            video=VIDEO,
            download=False,
            head=False,
        )
    # And the library answer of a failed track (a stale alias) is error 70 as well.
    with pytest.raises(StreamFailed):
        await streams(live)._library(direct(live, TRACK), download=False)


async def test_the_library_answer_needs_an_archived_file(live: Live) -> None:
    with pytest.raises(NotFound):
        await streams(live)._library(direct(live, f"yt:{VIDEO}"), download=False)
    add_pending(live)
    with pytest.raises(NotFound):
        await streams(live)._library(direct(live, TRACK), download=False)
    archive(live, TRACK, None)
    (live.services.settings.music_dir / "The Paper Lanterns" / "Glass Orchard.opus").unlink()
    with pytest.raises(NotFound):
        await streams(live)._library(direct(live, TRACK), download=False)


async def test_a_virtual_id_needs_its_catalog_record(live: Live) -> None:
    with pytest.raises(NotFound):
        streams(live)._enqueue(VirtualId("song", VIDEO), VIDEO, None, ANA.user_id)


# ------------------------------------------------------------------ caps


async def test_listener_cap_per_api_key(
    stream_settings: Settings, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UT_MAX_LISTENERS_PER_KEY", "1")
    monkeypatch.setenv("UT_LISTENER_RETRY_AFTER_S", "7")
    async with serve(stream_settings, clock) as live, anyio.create_task_group() as group:
        first = start(live, group)
        dl = await requested(live)
        dl.write(100)
        await until(lambda: len(first.body) == 100)
        capped = await live.client.get("/rest/stream", params=live.params(live.song(), f="xml"))
        assert capped.status_code == 503
        assert capped.headers["retry-after"] == "7"
        assert b'code="0"' in capped.content
        # Another key still gets in.
        other = start(live, group, key="utk_bob")
        await until(lambda: len(other.body) == 100)
        assert live.listeners(dl.job_id) == 2
        dl.finish()
        await first.done.wait()
        await other.done.wait()


async def test_listener_cap_per_job(
    stream_settings: Settings, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UT_MAX_LISTENERS_PER_JOB", "1")
    async with serve(stream_settings, clock) as live, anyio.create_task_group() as group:
        first = start(live, group)
        dl = await requested(live)
        capped = await live.client.get("/rest/stream", params=live.params(live.song(), "utk_bob"))
        assert capped.status_code == 503
        assert envelope_code(capped) == 0
        assert capped.headers["retry-after"] == "5"
        # The refused listener left nothing behind.
        assert live.listeners(dl.job_id) == 1
        assert live.services.inflight.listeners("stream:key:k-bob") == 0
        dl.finish()
        await first.done.wait()


async def test_a_password_user_is_capped_per_user(
    stream_settings: Settings, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UT_MAX_LISTENERS_PER_KEY", "1")
    async with serve(stream_settings, clock) as live, anyio.create_task_group() as group:
        params = {"u": "carl", "p": "carl-password", "id": live.song(), "f": "json"}
        first = Listening()
        group.start_soon(first.run, live.client, "/rest/stream", params, {})
        dl = await requested(live)
        # The download is requested before the stream is admitted: wait for the admission
        # (the slot of the user, since a password user has no key id), never race it.
        slot = "stream:key:user:0199d6a2-4c1e-7b3a-9f10-2a6c8e01e003"
        await until(lambda: live.services.inflight.listeners(slot) == 1)
        capped = await live.client.get("/rest/stream", params=params)
        assert capped.status_code == 503
        dl.finish()
        await first.done.wait()


# ------------------------------------------------------------------ clients that go away


async def test_a_client_that_hangs_up_frees_its_slot(
    stream_settings: Settings, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UT_MAX_LISTENERS_PER_KEY", "1")
    async with serve(stream_settings, clock) as live, anyio.create_task_group() as group:
        first = start(live, group)
        dl = await requested(live)
        dl.write(100)
        await until(lambda: len(first.body) == 100)
        # It hangs up while the body waits for the next report.
        first.stop.set()
        await first.done.wait()
        await until(lambda: live.listeners(dl.job_id) == 0)
        again = start(live, group)
        await until(lambda: len(again.body) == 100)
        dl.finish()
        await again.done.wait()
    assert bytes(again.body) == AUDIO


async def test_a_client_that_hangs_up_before_the_first_byte_frees_its_slot(
    live: Live, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "DISCONNECT_CHECK_S", 0.05)
    async with anyio.create_task_group() as group:
        start(live, group)
        dl = await requested(live)
        await until(lambda: live.listeners(dl.job_id) == 1)
        group.cancel_scope.cancel()
    await until(lambda: live.listeners(dl.job_id) == 0)


# ------------------------------------------------------------------ archived, pending, unknown


async def test_a_song_archived_before_its_first_byte_comes_from_the_library(live: Live) -> None:
    async with anyio.create_task_group() as group:
        listening = start(live, group, endpoint="download")
        dl = await requested(live)
        track_id = dl.claimed.job.track_id
        archive(live, track_id, dl.job_id)
        await listening.done.wait()
    assert listening.status == 200
    assert bytes(listening.body) == b"archived" * 10
    assert listening.headers["accept-ranges"] == "bytes"
    assert "Glass Orchard.opus" in listening.headers["content-disposition"]
    await until(lambda: live.listeners(dl.job_id) == 0)


async def test_a_pending_track_gets_its_job_at_stream_priority(live: Live) -> None:
    add_pending(live)
    live.services.jobs.enqueue(track_id=TRACK, video_id=VIDEO, priority=PRIORITY_KEEP)
    async with anyio.create_task_group() as group:
        listening = start(live, group, song=TRACK)
        await until(lambda: (job := live.job()) is not None and job.priority == PRIORITY_STREAM)
        dl = live.download()
        dl.finish()
        await listening.done.wait()
    assert bytes(listening.body) == AUDIO
    assert live.one("SELECT COUNT(*) FROM jobs") == 1


async def test_a_pending_track_without_a_video_is_not_found(live: Live) -> None:
    add_pending(live, video=None)
    r = await live.client.get("/rest/stream", params=live.params(TRACK))
    assert r.status_code == 200
    assert envelope_code(r) == 70


async def test_an_unknown_external_song_is_not_found(live: Live) -> None:
    r = await live.client.get("/rest/stream", params=live.params("yt:Zz9Zz9Zz9Zz"))
    assert r.status_code == 200
    assert envelope_code(r) == 70
    assert live.one("SELECT COUNT(*) FROM tracks") == 0


async def test_server_info_announces_streaming(live: Live) -> None:
    caps = (await live.client.get("/ut/v1/server")).json()["capabilities"]
    assert caps["streamingWhileDownloading"] is True


async def test_another_song_is_another_job(live: Live) -> None:
    async with anyio.create_task_group() as group:
        first = start(live, group)
        second = start(live, group, song=f"yt:{OTHER_VIDEO}")
        await until(lambda: live.one("SELECT COUNT(*) FROM jobs") == 2)
        group.cancel_scope.cancel()
    assert not first.body
    assert not second.body
    assert isinstance(first.error, httpx.HTTPError | None)


async def test_head_of_an_unknown_external_song_is_not_found(live: Live) -> None:
    with pytest.raises(NotFound):
        await streams(live).serve(
            direct(live, "yt:Zz9Zz9Zz9Zz", "HEAD"),
            VirtualId("song", "Zz9Zz9Zz9Zz"),
            video="Zz9Zz9Zz9Zz",
            download=False,
            head=True,
        )


async def test_a_song_too_long_to_download_is_never_streamed(live: Live) -> None:
    long = replace(FakeMusicCatalog().tracks[VIDEO], duration_s=3 * 3600)
    with pytest.raises(InvalidParameter):
        streams(live)._enqueue(VirtualId("song", VIDEO), VIDEO, long, ANA.user_id)
    assert live.one("SELECT COUNT(*) FROM tracks") == 0
    assert live.job() is None
