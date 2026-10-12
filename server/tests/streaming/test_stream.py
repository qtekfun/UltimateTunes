# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`stream`/`download` of songs without an archived file, against a live api (RF-05, SPEC
section 11, contracts/opensubsonic-subset.yaml): the bytes arrive as the worker reports them."""

import anyio
import httpx
import pytest

from tests.streaming.harness import AUDIO, VIDEO, Download, Listening, Live, until
from ultimatetunes.jobs.queue import PRIORITY_STREAM
from ultimatetunes.streaming import service

pytestmark = pytest.mark.anyio


def start(  # noqa: PLR0913 - test knobs
    live: Live,
    group: anyio.abc.TaskGroup,
    *,
    key: str = "utk_ana",
    song: str | None = None,
    endpoint: str = "stream",
    headers: dict[str, str] | None = None,
) -> Listening:
    listening = Listening()
    group.start_soon(
        listening.run,
        live.client,
        f"/rest/{endpoint}",
        live.params(song or live.song(), key),
        headers or {},
    )
    return listening


async def requested(live: Live) -> Download:
    """Waits until the stream requested the job, then claims it like a worker."""
    await until(lambda: live.job() is not None)
    return live.download()


def envelope_code(response: httpx.Response) -> int:
    return int(response.json()["subsonic-response"]["error"]["code"])


async def test_first_play_requests_the_song_and_streams_it_as_it_grows(live: Live) -> None:
    async with anyio.create_task_group() as group:
        listening = start(live, group)
        dl = await requested(live)
        job = live.job()
        assert job is not None
        assert job.priority == PRIORITY_STREAM
        # The yt: id became a pending track with its alias (contracts/ids.md).
        assert live.one("SELECT status FROM tracks WHERE yt_video_id = ?", (VIDEO,)) == "pending"
        assert live.one("SELECT COUNT(*) FROM track_aliases WHERE alias = ?", (f"yt:{VIDEO}",)) == 1
        # Nothing is answered before the first byte.
        dl.report()
        await anyio.sleep(0.2)
        assert not listening.started.is_set()
        dl.write(100)
        await listening.started.wait()
        assert listening.status == 200
        assert listening.headers["content-length"] == str(len(AUDIO))
        assert listening.headers["accept-ranges"] == "bytes"
        assert listening.headers["content-type"] == "audio/webm"
        assert listening.headers["cache-control"] == "no-store"
        assert "content-disposition" not in listening.headers
        await until(lambda: len(listening.body) == 100)
        assert live.listeners(dl.job_id) == 1
        dl.write(400)
        await until(lambda: len(listening.body) == 500)
        dl.finish()
        await listening.done.wait()
    assert listening.error is None
    assert bytes(listening.body) == AUDIO
    await until(lambda: live.listeners(dl.job_id) == 0)


async def test_two_clients_share_one_download(live: Live) -> None:
    async with anyio.create_task_group() as group:
        ana = start(live, group)
        dl = await requested(live)
        dl.write(200)
        await until(lambda: len(ana.body) == 200)
        bob = start(live, group, key="utk_bob", endpoint="download")
        await until(lambda: len(bob.body) == 200)
        assert live.listeners(dl.job_id) == 2
        assert bob.headers["content-disposition"].startswith('attachment; filename="')
        assert f"{VIDEO}.webm" in bob.headers["content-disposition"]
        dl.finish()
        await ana.done.wait()
        await bob.done.wait()
    assert bytes(ana.body) == bytes(bob.body) == AUDIO
    assert live.one("SELECT COUNT(*) FROM jobs") == 1


async def test_a_failure_mid_stream_cuts_the_transfer_and_retries_get_error_70(
    live: Live, caplog: pytest.LogCaptureFixture
) -> None:
    async with anyio.create_task_group() as group:
        listening = start(live, group)
        dl = await requested(live)
        dl.write(300)
        await until(lambda: len(listening.body) == 300)
        dl.fail()
        await listening.done.wait()
    # Cut before Content-Length: the client sees a broken transfer, never a short success.
    assert isinstance(listening.error, httpx.RemoteProtocolError)
    assert len(listening.body) == 300
    # One warning says why; it is not an unexpected error of the app.
    assert "stream of job" in caplog.text
    assert "unhandled error" not in caplog.text
    again = await live.client.get("/rest/stream", params=live.params(live.song()))
    assert again.status_code == 404
    assert envelope_code(again) == 70
    await until(lambda: live.listeners(dl.job_id) == 0)


async def test_a_failure_before_the_first_byte_is_error_70(live: Live) -> None:
    async with anyio.create_task_group() as group:
        listening = start(live, group)
        dl = await requested(live)
        dl.fail()
        await listening.done.wait()
    assert listening.status == 404
    assert listening.error is None
    assert b'"code":70' in bytes(listening.body).replace(b" ", b"")


async def test_unknown_size_is_chunked_and_ignores_range(live: Live) -> None:
    async with anyio.create_task_group() as group:
        listening = start(live, group, headers={"Range": "bytes=100-"})
        dl = await requested(live)
        dl.expected_size = None
        dl.write(100)
        await listening.started.wait()
        assert listening.status == 200
        assert "content-length" not in listening.headers
        assert listening.headers["transfer-encoding"] == "chunked"
        assert listening.headers["accept-ranges"] == "none"
        await until(lambda: len(listening.body) == 100)
        dl.finish()
        await listening.done.wait()
    assert listening.error is None
    assert bytes(listening.body) == AUDIO


async def test_a_chunked_stream_is_cut_without_its_final_chunk(live: Live) -> None:
    async with anyio.create_task_group() as group:
        listening = start(live, group)
        dl = await requested(live)
        dl.expected_size = None
        dl.write(100)
        await until(lambda: len(listening.body) == 100)
        dl.fail()
        await listening.done.wait()
    assert isinstance(listening.error, httpx.RemoteProtocolError)


async def test_range_on_the_growing_file(live: Live) -> None:
    async with anyio.create_task_group() as group:
        first = start(live, group)
        dl = await requested(live)
        dl.write(100)
        await until(lambda: len(first.body) == 100)
        # The headers come at once; the bytes once the writer reaches them.
        ahead = start(live, group, headers={"Range": "bytes=600-799"})
        await ahead.started.wait()
        assert ahead.status == 206
        assert ahead.headers["content-range"] == f"bytes 600-799/{len(AUDIO)}"
        assert ahead.headers["content-length"] == "200"
        assert ahead.headers["accept-ranges"] == "bytes"
        dl.write(600)
        await until(lambda: len(ahead.body) == 100)
        dl.write(100)
        await ahead.done.wait()
        assert ahead.error is None
        assert bytes(ahead.body) == AUDIO[600:800]
        past = await live.client.get(
            "/rest/stream", params=live.params(live.song()), headers={"Range": "bytes=5000-"}
        )
        assert past.status_code == 416
        assert past.headers["content-range"] == f"bytes */{len(AUDIO)}"
        assert past.content == b""
        dl.finish()
        await first.done.wait()
    assert bytes(first.body) == AUDIO


async def test_an_end_indexed_format_is_served_only_once_complete(live: Live) -> None:
    async with anyio.create_task_group() as group:
        listening = start(live, group)
        dl = await requested(live)
        dl.progressive = False
        dl.format_id = "140"
        dl.content_type = "audio/mp4"
        dl.write(500)
        await anyio.sleep(0.3)
        assert not listening.started.is_set()
        dl.finish()
        await listening.done.wait()
    assert listening.status == 200
    assert listening.headers["content-type"] == "audio/mp4"
    assert bytes(listening.body) == AUDIO


async def test_a_final_size_other_than_announced_cuts_the_stream(live: Live) -> None:
    async with anyio.create_task_group() as group:
        listening = start(live, group)
        dl = await requested(live)
        dl.data = AUDIO[:900]
        dl.write(100)
        await until(lambda: len(listening.body) == 100)
        dl.finish()
        await listening.done.wait()
    assert isinstance(listening.error, httpx.RemoteProtocolError)
    assert len(listening.body) < len(AUDIO)


async def test_a_retry_with_the_same_bytes_continues_the_stream(live: Live) -> None:
    async with anyio.create_task_group() as group:
        listening = start(live, group)
        dl = await requested(live)
        dl.write(300)
        await until(lambda: len(listening.body) == 300)
        dl.fail("network_error", retryable=True)
        job = live.job()
        assert job is not None
        assert job.state == "queued"
        await anyio.sleep(0.2)
        assert not listening.done.is_set()
        live.clock.advance(3600)
        retry = live.download()
        assert retry.claimed.job.staging_dir.endswith("/2")
        retry.write(200)  # behind the listener: nothing new for it yet
        await anyio.sleep(0.2)
        assert len(listening.body) == 300
        retry.finish()
        await listening.done.wait()
    assert listening.error is None
    assert bytes(listening.body) == AUDIO


async def test_a_retry_with_another_format_cuts_the_stream(live: Live) -> None:
    async with anyio.create_task_group() as group:
        listening = start(live, group)
        dl = await requested(live)
        dl.write(300)
        await until(lambda: len(listening.body) == 300)
        dl.fail("network_error", retryable=True)
        live.clock.advance(3600)
        retry = live.download()
        retry.format_id = "140"
        retry.write(100)
        await listening.done.wait()
    assert isinstance(listening.error, httpx.RemoteProtocolError)


async def test_a_listener_finds_the_file_renamed_before_the_report(live: Live) -> None:
    async with anyio.create_task_group() as group:
        first = start(live, group)
        dl = await requested(live)
        dl.write(100)
        await until(lambda: len(first.body) == 100)
        # The worker renamed the file; its `finished` report is still on its way.
        live.services.staging.rename(dl.part, dl.final)
        late = start(live, group, key="utk_bob")
        await until(lambda: len(late.body) == 100)
        # The worker writes on through its open handle (same inode), then reports.
        with live.services.staging.open_write(dl.final, append=True) as out:
            out.write(AUDIO[100:])
        dl.written = len(AUDIO)
        dl.finished = True
        dl.report(state="tagging")
        await first.done.wait()
        await late.done.wait()
    assert bytes(first.body) == bytes(late.body) == AUDIO


async def test_reported_bytes_that_never_appear_cut_the_stream(
    live: Live, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "MISSING_BYTES_GRACE_S", 0.2)
    async with anyio.create_task_group() as group:
        listening = start(live, group)
        dl = await requested(live)
        dl.write(100)
        await until(lambda: len(listening.body) == 100)
        dl.written = 500  # reported, but not on disk
        dl.report()
        await listening.done.wait()
    assert isinstance(listening.error, httpx.RemoteProtocolError)
    assert len(listening.body) == 100


async def test_a_vanished_staging_file_cuts_the_stream(
    live: Live, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "MISSING_BYTES_GRACE_S", 0.2)
    async with anyio.create_task_group() as group:
        first = start(live, group)
        dl = await requested(live)
        dl.write(100)
        await until(lambda: len(first.body) == 100)
        live.services.staging.delete(dl.part)
        late = start(live, group, key="utk_bob")
        await late.done.wait()
        first.stop.set()
    assert late.status == 200
    assert isinstance(late.error, httpx.RemoteProtocolError)
    assert not late.body


async def test_an_unreadable_staging_file_cuts_the_stream(live: Live) -> None:
    async with anyio.create_task_group() as group:
        dl_task = start(live, group)
        dl = await requested(live)
        # A directory where the file should be: reading it is an I/O error.
        (live.services.settings.staging_dir / dl.part).mkdir(parents=True)
        dl.written = 100
        dl.report()
        await dl_task.done.wait()
    assert isinstance(dl_task.error, httpx.RemoteProtocolError)


async def test_a_failing_cleanup_never_breaks_a_stream(
    live: Live, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(job_id: str) -> int:
        raise RuntimeError("database is locked")

    monkeypatch.setattr(live.client_app.state.staging_janitor, "clean_job", broken)
    async with anyio.create_task_group() as group:
        listening = start(live, group)
        dl = await requested(live)
        dl.finish()
        await listening.done.wait()
    assert bytes(listening.body) == AUDIO
    await until(lambda: "staging cleanup of job" in caplog.text)
