# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Production polish of the panel: what needs attention in the overview (low disk space, the
YouTube Music budget, failures), each user's share of the download limits and catalog budgets,
paged lists (queue, needs review, audit log) with their filters, marking a track reviewed, and
confirmations before destructive actions. Access rules of the new route are covered by
`test_access.py`, which enumerates every route."""

import re
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from tests.admin.conftest import People
from tests.admin.test_pages import add_track, services_of
from ultimatetunes.admin import routes
from ultimatetunes.admin.repository import PAGE_SIZE
from ultimatetunes.core.clock import FakeClock, format_ts
from ultimatetunes.core.limits import DownloadLimits
from ultimatetunes.core.storage import Usage
from ultimatetunes.jobs.gate import LOW_DISK_KEY, hour_start
from ultimatetunes.search import guard
from ultimatetunes.search.settings import SearchSettings

GIB = 1024**3


def admin_state(client: TestClient) -> routes.AdminState:
    found: routes.AdminState = client.app.state.admin  # type: ignore[attr-defined]
    return found


def put_setting(client: TestClient, key: str, value: str) -> None:
    services = services_of(client)
    with services.db.transaction() as conn:
        conn.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, value),
        )


# ---------------------------------------------------------------------- overview


def test_overview_with_nothing_to_report(
    client: TestClient, admin_csrf: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = services_of(client)
    roomy = Usage(total_bytes=100 * GIB, used_bytes=10 * GIB, free_bytes=90 * GIB)
    monkeypatch.setattr(services.library, "usage", lambda: roomy)
    monkeypatch.setattr(services.staging, "usage", lambda: roomy)
    with services.db.transaction() as conn:
        conn.execute(
            "INSERT INTO worker_status (worker_id, version, ytdlp_version, last_seen_at)"
            " VALUES ('w1', '1.0.0', '2026.09.01', ?)",
            (format_ts(services.clock.now()),),
        )
    page = client.get("/admin")
    assert page.status_code == 200
    assert "Everything looks fine." in page.text
    assert "90.0 GiB" in page.text
    assert "yt-dlp 2026.09.01" in page.text
    assert "Shared request budget: 6.0 / 6.0" in page.text
    assert 'class="skip" href="#main"' in page.text
    assert "<footer" in page.text


def test_overview_lists_what_needs_attention(
    client: TestClient, admin_csrf: str, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = services_of(client)
    add_track(services, "t1", title="Weak match", needs_review=True)
    add_track(services, "t2", title="Broken")
    job = services.jobs.enqueue(track_id="t2", video_id="bbbbbbbbbbb", priority=30)
    with services.db.transaction() as conn:
        conn.execute("UPDATE jobs SET state = 'failed' WHERE id = ?", (job.id,))
        conn.execute(
            "INSERT INTO canary_runs (id, source, ran_at, ok, message)"
            " VALUES ('c1', 'api', ?, 0, 'search failed')",
            (format_ts(clock.now()),),
        )
    for _ in range(6):
        services.rate_limiter.hit(guard.BUCKET, routes.ytm_limit(SearchSettings()))
    put_setting(client, LOW_DISK_KEY, "2026-10-12T07:00:00.000Z")
    page = client.get("/admin").text
    assert "Downloads are paused: low disk space since 2026-10-12T07:00:00.000Z" in page
    assert "The shared YouTube Music request budget is used up" in page
    assert "The last canary run failed" in page
    assert "No worker has reported yet" in page
    assert 'href="/admin/jobs?state=failed">1 failed downloads' in page
    assert "1 tracks need review" in page
    assert "Everything looks fine." not in page
    es = client.get("/admin", headers={"Accept-Language": "es"}).text
    assert "Requiere atención" in es
    assert "Las descargas están en pausa" in es


def test_overview_flags_a_low_volume_before_the_gate_does(
    client: TestClient, admin_csrf: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = services_of(client)
    tight = Usage(total_bytes=10 * GIB, used_bytes=9 * GIB, free_bytes=GIB)

    def gone() -> Usage:
        raise OSError("unmounted")

    monkeypatch.setattr(services.library, "usage", lambda: tight)
    monkeypatch.setattr(services.staging, "usage", gone)
    page = client.get("/admin").text
    assert "/music is below the free-space minimum (2.0 GiB)" in page
    assert "/staging is below the free-space minimum" in page
    assert ">?</td>" in page


# ---------------------------------------------------------------------- users


def test_users_show_download_usage_and_catalog_budgets(
    client: TestClient, admin_csrf: str, people: People, clock: FakeClock
) -> None:
    services = services_of(client)
    admin_state(client).limits = DownloadLimits(
        max_queued_jobs_per_user=2, max_download_bytes_per_day_per_user=GIB
    )
    add_track(services, "t1")
    add_track(services, "t2")
    services.jobs.enqueue(
        track_id="t1", video_id="aaaaaaaaaaa", requested_by=people.bob.id, priority=30
    )
    services.jobs.enqueue(
        track_id="t2", video_id="bbbbbbbbbbb", requested_by=people.bob.id, priority=30
    )
    with services.db.transaction() as conn:
        for hours_ago, amount in ((1, GIB // 2), (30, GIB)):
            conn.execute(
                "INSERT INTO download_usage (user_id, hour_start, bytes) VALUES (?, ?, ?)",
                (people.bob.id, hour_start(clock.now() - timedelta(hours=hours_ago)), amount),
            )
    catalog = guard.user_limit(SearchSettings())
    for _ in range(55):
        services.rate_limiter.hit(guard.USER_BUCKET + people.bob.id, catalog)
    page = client.get("/admin/users").text
    bob = _row(page, "bob")
    assert "2 / 2" in bob
    assert 'class="meter bad"' in bob
    # Only the last 24 hours count.
    assert "512.0 MiB / 1.0 GiB" in bob
    assert '<span class="warn">5/60</span>' in bob
    assert "20/20" in bob
    alice = _row(page, "alice")
    assert "0 / 2" in alice
    assert "(you)" in alice
    assert "60/60" in alice


def _row(page: str, username: str) -> str:
    found = re.search(rf"<tr>\s*<td[^>]*><strong>{username}</strong>.*?</tr>", page, re.S)
    assert found, username
    return found.group(0)


def test_destructive_actions_ask_first(client: TestClient, admin_csrf: str, people: People) -> None:
    services = services_of(client)
    created = client.post(
        "/admin/keys",
        data={
            "csrf": admin_csrf,
            "user_id": people.bob.id,
            "name": "Phone",
            "server_url": "https://music.example.com",
        },
    )
    assert "point it at this code" in created.text
    assert "cannot scan" not in created.text
    keys = client.get("/admin/keys").text
    assert 'data-confirm="Revoke the key of Phone?' in keys
    users = client.get("/admin/users").text
    assert 'data-confirm="Disable bob?' in users
    assert 'data-confirm="Change the role of bob?"' in users
    add_track(services, "t1", title="Queued one")
    services.jobs.enqueue(track_id="t1", video_id="aaaaaaaaaaa", priority=30)
    assert 'data-confirm="Cancel the download of Queued one?"' in client.get("/admin/jobs").text
    add_track(services, "t2", title="Odd", needs_review=True)
    library = client.get("/admin/library").text
    assert 'data-confirm="Delete Odd from the library and from disk?' in library


# ---------------------------------------------------------------------- paged lists


def test_queue_pages_keep_the_filter(client: TestClient, admin_csrf: str, people: People) -> None:
    services = services_of(client)
    for n in range(PAGE_SIZE + 2):
        add_track(services, f"t{n}", title=f"Song {n}")
        services.jobs.enqueue(
            track_id=f"t{n}", video_id=f"v{n:010d}", requested_by=people.bob.id, priority=30
        )
    first = client.get("/admin/jobs?state=queued").text
    assert first.count('<code class="muted">v') == PAGE_SIZE
    assert 'href="?state=queued&amp;page=2"' in first
    assert 'hx-get="/admin/jobs/table?state=queued&amp;page=1"' in first
    assert "Newer" not in first
    assert ">bob</td>" in first
    second = client.get("/admin/jobs/table?state=queued&page=2").text
    assert second.count('<code class="muted">v') == 2
    assert 'href="?state=queued&amp;page=1"' in second
    assert "Older" not in second
    assert 'hx-get="/admin/jobs/table?state=queued&amp;page=2"' in second
    # A page out of range shows an empty page; nonsense is page 1.
    assert "No downloads in this state." in client.get("/admin/jobs?state=queued&page=9").text
    assert client.get("/admin/jobs?page=-3").text.count('<code class="muted">v') == PAGE_SIZE
    assert "Page 1000" in client.get("/admin/jobs?page=9999").text
    assert "No downloads here." in client.get("/admin/jobs?page=9999").text
    # Not ASCII digits, or too long to be a page: page 1.
    for raw in ("\N{SUPERSCRIPT TWO}", "9" * 5000, "12345", "\N{ARABIC-INDIC DIGIT TWO}"):
        listed = client.get("/admin/jobs", params={"page": raw}).text
        assert "Page 1" in listed
        assert listed.count('<code class="muted">v') == PAGE_SIZE


def test_mark_reviewed(client: TestClient, admin_csrf: str) -> None:
    services = services_of(client)
    add_track(services, "t1", title="Weak match", needs_review=True)
    add_track(services, "t2", title="Fine")
    page = client.get("/admin/library").text
    assert 'action="/admin/library/tracks/t1/reviewed"' in page
    r = client.post("/admin/library/tracks/t1/reviewed", data={"csrf": admin_csrf})
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/library?done=track_reviewed"
    after = client.get(r.headers["location"]).text
    assert "Marked as reviewed." in after
    assert "No track needs review." in after
    with services.db.read() as conn:
        flag = conn.execute("SELECT needs_review FROM tracks WHERE id = 't1'").scalar()
    assert flag == 0
    for track in ("t1", "t2", "nope"):
        again = client.post(f"/admin/library/tracks/{track}/reviewed", data={"csrf": admin_csrf})
        assert again.status_code == 404
        assert "No such track needs review" in again.text
    entries = admin_state(client).auth.recent_audit(10)
    assert [e.target_id for e in entries if e.action == "track.review"] == ["t1"]


def test_needs_review_is_paged(client: TestClient, admin_csrf: str) -> None:
    services = services_of(client)
    for n in range(PAGE_SIZE + 1):
        add_track(services, f"t{n}", title=f"Weak {n}", needs_review=True)
    first = client.get("/admin/library").text
    assert first.count('/reviewed"') == PAGE_SIZE
    assert 'href="?page=2"' in first
    second = client.get("/admin/library?page=2&q=weak").text
    assert second.count('/reviewed"') == 1
    assert 'href="?q=weak&amp;page=1"' in second


def test_audit_log_filters_and_pages(client: TestClient, admin_csrf: str, people: People) -> None:
    services = services_of(client)
    add_track(services, "t1", needs_review=True)
    client.post("/admin/library/tracks/t1/reviewed", data={"csrf": admin_csrf})
    page = client.get("/admin/audit").text
    assert '<option value="track.review">track.review</option>' in page
    assert f'<option value="{people.bob.id}">bob</option>' in page
    only = client.get("/admin/audit", params={"action": "track.review"}).text
    assert "<code>track.review</code>" in only
    assert "<code>admin.login</code>" not in only
    assert '<option value="track.review" selected>' in only
    assert 'href="/admin/audit">Clear' in only
    nobody = client.get("/admin/audit", params={"actor": people.bob.id}).text
    assert "Nothing here." in nobody
    # Unknown filters are ignored rather than echoed.
    ignored = client.get("/admin/audit", params={"action": "<x>", "actor": "nope"}).text
    assert "<code>admin.login</code>" in ignored
    assert "&lt;x&gt;" not in ignored
    for n in range(PAGE_SIZE):
        client.post(
            "/admin/users/" + people.bob.id,
            data={"csrf": admin_csrf, "action": "enable" if n % 2 else "disable"},
        )
    alice = people.alice.id
    first = client.get("/admin/audit", params={"actor": alice}).text
    assert first.count("<tr>") == PAGE_SIZE + 1  # the header row too
    assert f'href="?actor={alice}&amp;page=2"' in first
    # Sign-in, the review and 50 account changes: 52 entries of alice.
    second = client.get("/admin/audit", params={"actor": alice, "page": "2"}).text
    assert second.count("<tr>") == 3
    assert "Older" not in second
