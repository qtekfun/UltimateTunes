# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Notifications (SPEC RF-13): the admin sets one https target; failed downloads and canary
runs are sent there and nowhere else. Outbound HTTP goes to a recording transport."""

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.admin.conftest import RecordingTransport, public_dns
from ultimatetunes.admin import notify
from ultimatetunes.admin.notify import (
    KEY_CURSOR,
    Message,
    NotificationSweep,
    Sender,
    Target,
    check_url,
    compose,
    load_target,
    save_target,
)
from ultimatetunes.admin.repository import AdminRepository
from ultimatetunes.core.clock import FakeClock, format_ts
from ultimatetunes.core.limits import DownloadLimits
from ultimatetunes.core.services import Services
from ultimatetunes.db import Database
from ultimatetunes.errors import InvalidParameter
from ultimatetunes.jobs.gate import DownloadGate

NTFY = "https://ntfy.example.net/ut-alerts-1234"


@pytest.mark.parametrize(
    "url",
    [
        "http://ntfy.example.net/topic",
        "ftp://ntfy.example.net/topic",
        "https://",
        "https://user:pw@ntfy.example.net/topic",
        "https://ntfy.example.net/a b",
        "https://ntfy.example.net/\x00",
        "",
        "https://ntfy.example.net/" + "a" * 2048,
        "file:///etc/passwd",
        "javascript:alert(1)",
        "https://localhost/topic",
        "https://ntfy.localhost./topic",
        "https://127.0.0.1/topic",
        "https://[::1]/topic",
        "https://169.254.169.254/latest/meta-data",
        "https://[fe80::1]/x",
        "https://0.0.0.0/x",
        "https://224.0.0.1/x",
        "https://[::ffff:127.0.0.1]/x",
    ],
)
def test_only_plain_https_urls(url: str) -> None:
    with pytest.raises(InvalidParameter):
        check_url(url)


def test_check_url_and_kind() -> None:
    assert check_url(f"  {NTFY} ") == NTFY
    # A self-hosted ntfy on the LAN is fine.
    assert check_url("https://192.168.1.30/alerts") == "https://192.168.1.30/alerts"
    assert notify.check_kind("webhook") == "webhook"
    with pytest.raises(InvalidParameter):
        notify.check_kind("email")


def test_save_load_and_clear_target(db: Database, clock: FakeClock) -> None:
    assert load_target(db) is None
    save_target(db, clock, Target("ntfy", NTFY))
    assert load_target(db) == Target("ntfy", NTFY)
    with db.read() as conn:
        assert AdminRepository(conn).setting(KEY_CURSOR) == format_ts(clock.now())
    clock.advance(10)
    save_target(db, clock, Target("webhook", NTFY))
    with db.read() as conn:
        # Changing the target keeps the cursor: nothing is sent twice.
        assert AdminRepository(conn).setting(KEY_CURSOR) == "2026-10-12T08:00:00.000Z"
    save_target(db, clock, None)
    assert load_target(db) is None
    with db.read() as conn:
        assert AdminRepository(conn).setting(KEY_CURSOR) is None


def test_compose() -> None:
    assert compose([], []) is None
    jobs = [(f"Song {n}", "Artist", "unavailable" if n else None) for n in range(12)]
    message = compose(jobs, [("worker", None), ("api", "layout changed")])
    assert message is not None
    assert "12 download(s) failed:" in message.body
    assert "- Artist - Song 0\n" in message.body
    assert "(unavailable)" in message.body
    assert "Song 11" not in message.body
    assert "- worker: no message" in message.body
    assert "- api: layout changed" in message.body


def _run(coro: object) -> object:
    return asyncio.run(coro)  # type: ignore[arg-type]


def test_sender_ntfy_and_webhook() -> None:
    transport = RecordingTransport()
    sender = Sender(transport, public_dns)
    message = Message("Ünïcode\ntitle", "body text")
    assert _run(sender.send(Target("ntfy", NTFY), message)) is True
    ntfy = transport.requests[-1]
    assert str(ntfy.url) == NTFY
    assert ntfy.headers["title"] == "?n?code title"
    assert ntfy.content == b"body text"
    assert _run(sender.send(Target("webhook", NTFY), message)) is True
    hook = transport.requests[-1]
    assert json.loads(hook.content) == {
        "source": "ultimatetunes",
        "title": "Ünïcode\ntitle",
        "message": "body text",
    }


def test_sender_failures_are_logged_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    redirect = RecordingTransport(status=302)
    assert _run(Sender(redirect, public_dns).send(Target("ntfy", NTFY), Message("t", "b"))) is False
    assert len(redirect.requests) == 1  # redirects are never followed

    class Broken(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("down")

    assert _run(Sender(Broken(), public_dns).send(Target("ntfy", NTFY), Message("t", "b"))) is False
    assert (
        _run(Sender(redirect, public_dns).send(Target("ntfy", "http://x"), Message("t", "b")))
        is False
    )
    # Checked again at send time (e.g. a row written before the rule): nothing goes out.
    loopback = Target("ntfy", "https://127.0.0.1/x")
    assert _run(Sender(redirect, public_dns).send(loopback, Message("t", "b"))) is False
    assert len(redirect.requests) == 1
    assert "ntfy.example.net" in caplog.text
    assert "ut-alerts-1234" not in caplog.text


@pytest.mark.parametrize(
    "addresses",
    [
        ["127.0.0.1"],
        ["203.0.113.80", "::1"],
        ["169.254.169.254"],
        ["0.0.0.0"],  # noqa: S104 - what a hostile name may resolve to
        ["fe80::1%eth0"],
        ["::ffff:127.0.0.1"],
        ["224.0.0.1"],
        [],
        ["not-an-address"],
    ],
)
def test_sender_refuses_names_resolving_to_its_own_network(
    addresses: list[str], caplog: pytest.LogCaptureFixture
) -> None:
    """Audit L6: a public name pointed at loopback or cloud metadata is caught at send time."""
    transport = RecordingTransport()

    async def resolve(host: str) -> list[str]:
        assert host == "ntfy.example.net"
        return addresses

    sender = Sender(transport, resolve)
    assert _run(sender.send(Target("ntfy", NTFY), Message("t", "b"))) is False
    assert transport.requests == []
    assert "ntfy.example.net" in caplog.text
    assert "ut-alerts-1234" not in caplog.text


def test_sender_resolution_failures_and_lan_targets(caplog: pytest.LogCaptureFixture) -> None:
    transport = RecordingTransport()

    async def nxdomain(host: str) -> list[str]:
        raise OSError("no such name")

    assert _run(Sender(transport, nxdomain).send(Target("ntfy", NTFY), Message("t", "b"))) is False
    assert "does not resolve" in caplog.text

    async def lan(host: str) -> list[str]:
        return ["192.168.1.30", "fd00::30"]

    # A self-hosted ntfy on the LAN is fine; an IP literal is not resolved at all.
    assert _run(Sender(transport, lan).send(Target("ntfy", NTFY), Message("t", "b"))) is True

    async def never(host: str) -> list[str]:
        raise AssertionError("IP literals are not resolved")

    literal = Target("ntfy", "https://192.168.1.30/alerts")
    assert _run(Sender(transport, never).send(literal, Message("t", "b"))) is True
    assert len(transport.requests) == 2


def test_system_resolver_reads_numeric_hosts() -> None:
    assert _run(notify.system_resolve("127.0.0.1")) == ["127.0.0.1"]


def _fail_job(services: Services, track: str, video: str) -> None:
    now = format_ts(services.clock.now())
    with services.db.transaction() as conn:
        conn.execute(
            "INSERT INTO tracks (id, status, title, title_norm, artist_name, created_at,"
            " updated_at)"
            " VALUES (?, 'failed', ?, ?, 'Someone', ?, ?)",
            (track, f"Title {track}", track, now, now),
        )
    job = services.jobs.enqueue(track_id=track, video_id=video, priority=30)
    with services.db.transaction() as conn:
        conn.execute(
            "UPDATE jobs SET state = 'failed', error_code = 'unavailable', finished_at = ?"
            " WHERE id = ?",
            (now, job.id),
        )


def test_sweep_sends_new_failures_once(services: Services, clock: FakeClock) -> None:
    transport = RecordingTransport()
    sweep = NotificationSweep(services.db, clock, Sender(transport, public_dns))
    _fail_job(services, "t0", "aaaaaaaaaaa")
    assert _run(sweep.run_once()) is False  # no target: nothing at all
    save_target(services.db, clock, Target("ntfy", NTFY))
    assert _run(sweep.run_once()) is False  # failures before the target are not sent
    clock.advance(5)
    _fail_job(services, "t1", "bbbbbbbbbbb")
    with services.db.transaction() as conn:
        conn.execute(
            "INSERT INTO canary_runs (id, source, ran_at, ok, message)"
            " VALUES ('c1', 'api', ?, 0, 'parse error')",
            (format_ts(clock.now()),),
        )
    clock.advance(5)
    assert _run(sweep.run_once()) is True
    body = transport.requests[-1].content.decode()
    assert "Title t1" in body
    assert "Title t0" not in body
    assert "parse error" in body
    clock.advance(5)
    assert _run(sweep.run_once()) is False
    assert len(transport.requests) == 1


def test_sweep_restarts_a_lost_cursor(services: Services, clock: FakeClock) -> None:
    sweep = NotificationSweep(services.db, clock, Sender(RecordingTransport(), public_dns))
    save_target(services.db, clock, Target("ntfy", NTFY))
    with services.db.transaction() as conn:
        AdminRepository(conn).delete_setting(KEY_CURSOR)
    assert _run(sweep.run_once()) is False
    with services.db.read() as conn:
        assert AdminRepository(conn).setting(KEY_CURSOR) is not None


def test_sweep_loop_survives_errors(
    services: Services, clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    sweep = NotificationSweep(services.db, clock, Sender(RecordingTransport(), public_dns))
    calls: list[int] = []

    async def flaky() -> bool:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("database busy")
        raise asyncio.CancelledError

    sweep.run_once = flaky  # type: ignore[method-assign]
    with pytest.raises(asyncio.CancelledError):
        _run(sweep.run_forever(0))
    assert len(calls) == 2
    assert "notification sweep failed" in caplog.text


# ---------------------------------------------------------------------- the page


def test_notifications_page(
    client: TestClient, admin_csrf: str, transport: RecordingTransport
) -> None:
    page = client.get("/admin/notifications")
    assert "Send a test notification" not in page.text
    no_target = client.post("/admin/notifications/test", data={"csrf": admin_csrf})
    assert no_target.status_code == 409
    bad = client.post(
        "/admin/notifications",
        data={"csrf": admin_csrf, "kind": "ntfy", "url": "http://ntfy.example.net/x"},
    )
    assert bad.status_code == 400
    assert "https://" in bad.text
    unknown = client.post(
        "/admin/notifications", data={"csrf": admin_csrf, "kind": "pager", "url": NTFY}
    )
    assert unknown.status_code == 400
    ok = client.post("/admin/notifications", data={"csrf": admin_csrf, "kind": "ntfy", "url": NTFY})
    assert ok.headers["location"] == "/admin/notifications?done=notify_saved"
    page = client.get("/admin/notifications")
    assert NTFY in page.text
    assert "Send a test notification" in page.text
    sent = client.post("/admin/notifications/test", data={"csrf": admin_csrf})
    assert sent.headers["location"].endswith("notify_sent")
    assert str(transport.requests[-1].url) == NTFY
    transport.status = 500
    failed = client.post("/admin/notifications/test", data={"csrf": admin_csrf})
    assert failed.headers["location"].endswith("notify_failed")
    off = client.post("/admin/notifications", data={"csrf": admin_csrf, "kind": "none"})
    assert off.status_code == 303
    audit = client.get("/admin/audit").text
    assert "notify.update" in audit
    assert "ntfy.example.net" in audit
    assert "ut-alerts-1234" not in audit


def test_compose_says_when_downloads_paused_for_disk_space() -> None:
    message = compose([], [], "2026-10-12T08:00:00.000Z")
    assert message is not None
    assert "Downloads paused since 2026-10-12T08:00:00.000Z" in message.body


def test_sweep_reports_a_low_disk_pause_once(services: Services, clock: FakeClock) -> None:
    transport = RecordingTransport()
    sweep = NotificationSweep(services.db, clock, Sender(transport, public_dns))
    save_target(services.db, clock, Target("ntfy", NTFY))
    _run(sweep.run_once())
    clock.advance(5)
    gate = DownloadGate(DownloadLimits(min_free_bytes=10), clock, (Full(),))  # type: ignore[arg-type]
    with services.db.transaction() as conn:
        assert gate.note_space(conn) is False
    clock.advance(5)
    assert _run(sweep.run_once()) is True
    assert "Downloads paused since" in transport.requests[-1].content.decode()
    clock.advance(5)
    assert _run(sweep.run_once()) is False


class Full:
    def free_bytes(self) -> int:
        return 0
