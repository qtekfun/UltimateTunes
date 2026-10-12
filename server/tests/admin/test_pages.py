# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""What each admin page shows and does: users, keys (with the QR code), downloads queue,
library, yt-dlp, audit log, and the public landing page. Templates escape user input."""

import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from tests.admin.conftest import People, csrf_of
from tests.auth.conftest import USER_PASSWORD
from ultimatetunes import __version__
from ultimatetunes.admin import qr
from ultimatetunes.admin.routes import (
    check_server_url,
    connect_uri,
    default_server_url,
    human_size,
)
from ultimatetunes.auth.service import AuthService
from ultimatetunes.core.clock import FakeClock, format_ts
from ultimatetunes.core.services import Services
from ultimatetunes.errors import InvalidParameter
from ultimatetunes.search.guard import BreakerState

XSS = "<script>alert(1)</script>"
ESCAPED = "&lt;script&gt;alert(1)&lt;/script&gt;"


def services_of(client: TestClient) -> Services:
    found: Services = client.app.state.services  # type: ignore[attr-defined]
    return found


# ---------------------------------------------------------------------- landing page


def test_landing_page_says_little(client: TestClient, people: People) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "UltimateTunes server is running." in r.text
    assert __version__ in r.text
    assert 'href="/admin"' in r.text
    for leak in ("alice", "bob", "/music", "stylesheet", "<script"):
        assert leak not in r.text
    es = client.get("/", headers={"Accept-Language": "es-ES,es;q=0.9,en;q=0.5"})
    assert "El servidor de UltimateTunes está funcionando." in es.text
    assert '<html lang="es">' in es.text


# ---------------------------------------------------------------------- users


def test_users_create_disable_role_password(
    client: TestClient, admin_csrf: str, people: People
) -> None:
    auth: AuthService = client.app.state.admin.auth  # type: ignore[attr-defined]
    page = client.get("/admin/users")
    assert "bob" in page.text
    assert "alice" in page.text
    r = client.post(
        "/admin/users",
        data={"csrf": admin_csrf, "username": "Carol", "password": "p" * 12, "role": "user"},
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/users?done=user_created"
    assert "User created." in client.get(r.headers["location"]).text
    carol = next(u for u in auth.list_users() if u.username == "carol")

    def act(**data: str) -> int:
        status: int = client.post(
            f"/admin/users/{carol.id}", data={"csrf": admin_csrf, **data}
        ).status_code
        return status

    assert act(action="disable") == 303
    assert auth.get_user(carol.id).is_disabled
    assert act(action="enable") == 303
    assert not auth.get_user(carol.id).is_disabled
    assert act(action="role", role="admin") == 303
    assert auth.get_user(carol.id).role == "admin"
    assert act(action="role", role="root") == 400
    assert act(action="password", password="short") == 400
    assert act(action="password", password="a new long passphrase") == 303
    assert act(action="explode") == 400
    missing = client.post(
        "/admin/users/0199d6a2-4c1e-7b3a-9f10-2a6c8e01c001",
        data={"csrf": admin_csrf, "action": "disable"},
    )
    assert missing.status_code == 404
    duplicate = client.post(
        "/admin/users",
        data={"csrf": admin_csrf, "username": "bob", "password": "p" * 12, "role": "user"},
    )
    assert duplicate.status_code == 409
    assert "That username is taken" in duplicate.text
    bad_name = client.post(
        "/admin/users",
        data={"csrf": admin_csrf, "username": XSS, "password": "p" * 12, "role": "user"},
    )
    assert bad_name.status_code == 400
    assert "<script>" not in bad_name.text


def test_admin_cannot_lock_themselves_out(
    client: TestClient, admin_csrf: str, people: People
) -> None:
    for data in ({"action": "disable"}, {"action": "role", "role": "user"}):
        r = client.post(f"/admin/users/{people.alice.id}", data={"csrf": admin_csrf, **data})
        assert r.status_code == 409
    assert client.get("/admin").status_code == 200


# ---------------------------------------------------------------------- keys and QR


def test_create_key_shows_it_once_with_a_qr(
    client: TestClient, admin_csrf: str, people: People
) -> None:
    r = client.post(
        "/admin/keys",
        data={
            "csrf": admin_csrf,
            "user_id": people.bob.id,
            "name": f"Pixel {XSS}",
            "server_url": "https://music.example.net/",
        },
    )
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    secret = re.search(r"utk_[A-Za-z0-9_-]{43}", r.text)
    assert secret is not None
    assert "<svg" in r.text
    assert 'class="qr"' in r.text
    assert ESCAPED in r.text
    assert XSS not in r.text
    # The QR holds the connect URI with the trailing slash dropped.
    expected = qr.to_svg(
        qr.encode(connect_uri("https://music.example.net", secret.group(0))),
        label="QR code to connect the app",
    )
    assert str(expected) in r.text
    # The key works for bob, and is never shown again.
    me = client.get("/ut/v1/me", headers={"X-Api-Key": secret.group(0)})
    assert me.status_code == 200
    assert me.json()["username"] == "bob"
    listing = client.get("/admin/keys")
    assert secret.group(0) not in listing.text
    assert secret.group(0)[:8] in listing.text or "utk_" in listing.text
    assert ESCAPED in listing.text


def test_create_key_errors(client: TestClient, admin_csrf: str, people: People) -> None:
    def create(**data: str) -> int:
        base = {
            "csrf": admin_csrf,
            "user_id": people.bob.id,
            "name": "Pixel",
            "server_url": "https://m.example.net",
        }
        status: int = client.post("/admin/keys", data={**base, **data}).status_code
        return status

    assert create(server_url="ftp://m.example.net") == 400
    assert create(server_url="http://m.example.net") == 400
    assert create(server_url="https://" + "a" * 200 + ".net") == 400
    # Fits the 120-character limit but not a QR code once percent-encoded: refused before any
    # key exists, so no live key is left unseen.
    assert create(server_url="https://m.example.net" + "/a" * 49) == 400
    auth: AuthService = client.app.state.admin.auth  # type: ignore[attr-defined]
    assert auth.list_keys(people.bob.id) == []
    assert create(user_id="0199d6a2-4c1e-7b3a-9f10-2a6c8e01c001") == 404
    assert create(name="") == 400


def test_server_url_and_connect_uri() -> None:
    assert check_server_url(" https://m.example.net:8443/ ") == "https://m.example.net:8443"
    for bad in (
        "m.example.net",
        "http://m.example.net",
        "javascript:alert(1)",
        "https://user:pw@m.example.net",
        "https://m.example.net/?a=1",
        "https://m.example.net/#x",
        "https://m.example.net/a b",
        "https://m.example.net/\x00",
    ):
        with pytest.raises(InvalidParameter):
            check_server_url(bad)
    uri = connect_uri("https://m.example.net:8443/tunes", "utk_abc-_")
    parts = urlsplit(uri)
    assert f"{parts.scheme}://{parts.netloc}" == "ultimatetunes://connect"
    assert parse_qs(parts.query) == {
        "url": ["https://m.example.net:8443/tunes"],
        "key": ["utk_abc-_"],
    }


def test_default_server_url(client: TestClient, admin_csrf: str) -> None:
    assert 'value="https://testserver"' in client.get("/admin/keys").text
    plain = Request(
        {
            "type": "http",
            "app": client.app,
            "scheme": "http",
            "server": ("192.168.1.5", 8044),
            "path": "/admin/keys",
            "root_path": "",
            "headers": [(b"host", b"192.168.1.5:8044")],
            "query_string": b"",
        }
    )
    # The app needs https: an http address is never suggested.
    assert default_server_url(plain) == ""
    state = client.app.state.admin  # type: ignore[attr-defined]
    object.__setattr__(state.settings, "admin_public_url", "https://tunes.example.ts.net")
    assert 'value="https://tunes.example.ts.net"' in client.get("/admin/keys").text


def test_revoke_key(client: TestClient, admin_csrf: str, people: People) -> None:
    auth: AuthService = client.app.state.admin.auth  # type: ignore[attr-defined]
    created = auth.create_key(people.bob.id, "Old phone", actor=None)
    r = client.post(f"/admin/keys/{created.key.id}/revoke", data={"csrf": admin_csrf})
    assert r.status_code == 303
    assert auth.list_keys(people.bob.id)[0].revoked_at is not None
    assert "Revoked" in client.get("/admin/keys").text
    missing = client.post(
        "/admin/keys/0199d6a2-4c1e-7b3a-9f10-2a6c8e01c001/revoke", data={"csrf": admin_csrf}
    )
    assert missing.status_code == 404


# ---------------------------------------------------------------------- library helpers


def add_album(services: Services, *, name: str = "Album", cover: str | None = None) -> str:
    now = format_ts(services.clock.now())
    artist_id, album_id = f"ar-{name}", f"al-{name}"
    with services.db.transaction() as conn:
        conn.execute(
            "INSERT INTO artists (id, name, name_norm, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (artist_id, f"Artist {name}", f"artist {name.lower()}", now, now),
        )
        conn.execute(
            "INSERT INTO albums (id, artist_id, name, name_norm, cover_path, created_at,"
            " updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (album_id, artist_id, name, name.lower(), cover, now, now),
        )
    return album_id


def add_track(  # noqa: PLR0913
    services: Services,
    track_id: str,
    *,
    title: str = "Song",
    album_id: str | None = None,
    path: str | None = None,
    needs_review: bool = False,
    size: int = 1000,
    video: str | None = None,
) -> str:
    now = format_ts(services.clock.now())
    with services.db.transaction() as conn:
        conn.execute(
            "INSERT INTO tracks (id, status, title, title_norm, artist_name, album_id, path,"
            " size_bytes, needs_review, yt_video_id, created_at, updated_at)"
            " VALUES (?, 'ready', ?, ?, 'Someone', ?, ?, ?, ?, ?, ?, ?)",
            (
                track_id,
                title,
                title.lower(),
                album_id,
                path,
                size,
                int(needs_review),
                video,
                now,
                now,
            ),
        )
    return track_id


def write_file(root: Path, rel: str, data: bytes = b"audio") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


# ---------------------------------------------------------------------- downloads queue


def test_jobs_list_filter_retry_cancel(
    client: TestClient, admin_csrf: str, clock: FakeClock
) -> None:
    services = services_of(client)
    add_track(services, "t1", title=f"First {XSS}")
    add_track(services, "t2", title="Second")
    add_track(services, "t3", title="Third")
    queued = services.jobs.enqueue(track_id="t1", video_id="aaaaaaaaaaa", priority=30)
    failed = services.jobs.enqueue(track_id="t2", video_id="bbbbbbbbbbb", priority=30)
    running = services.jobs.enqueue(track_id="t3", video_id="ccccccccccc", priority=10)
    with services.db.transaction() as conn:
        conn.execute(
            "UPDATE jobs SET state = 'failed', error_code = 'unavailable', finished_at = ?"
            " WHERE id = ?",
            (format_ts(clock.now()), failed.id),
        )
        conn.execute("UPDATE jobs SET priority = 1 WHERE id = ?", (queued.id,))
    claimed = services.jobs.claim("worker-1", lease_s=60)
    assert claimed is not None
    assert claimed.job.id == running.id

    page = client.get("/admin/jobs")
    assert ESCAPED in page.text
    assert XSS not in page.text
    assert 'hx-trigger="every 5s"' in page.text
    only_failed = client.get("/admin/jobs/table?state=failed")
    assert "Second" in only_failed.text
    assert "Third" not in only_failed.text
    assert "<html" not in only_failed.text
    assert "Second" in client.get("/admin/jobs?state=bogus").text

    # Retry only failed/cancelled; cancel only queued/running.
    assert (
        client.post(f"/admin/jobs/{queued.id}/retry", data={"csrf": admin_csrf}).status_code == 409
    )
    assert (
        client.post(f"/admin/jobs/{failed.id}/cancel", data={"csrf": admin_csrf}).status_code == 409
    )
    r = client.post(f"/admin/jobs/{failed.id}/retry", data={"csrf": admin_csrf})
    assert r.status_code == 303
    retried = services.jobs.get(failed.id)
    assert retried is not None
    assert retried.state == "queued"
    assert (
        client.post(f"/admin/jobs/{queued.id}/cancel", data={"csrf": admin_csrf}).status_code == 303
    )
    cancelled = services.jobs.get(queued.id)
    assert cancelled is not None
    assert cancelled.state == "cancelled"
    assert (
        client.post(f"/admin/jobs/{running.id}/cancel", data={"csrf": admin_csrf}).status_code
        == 303
    )
    leased = services.jobs.get(running.id)
    assert leased is not None
    assert leased.cancel_requested
    assert "cancel requested" in client.get("/admin/jobs").text
    for action in ("retry", "cancel"):
        missing = client.post(f"/admin/jobs/nope/{action}", data={"csrf": admin_csrf})
        assert missing.status_code == 404
    actions = [e.action for e in client.app.state.admin.auth.recent_audit(20)]  # type: ignore[attr-defined]
    assert actions.count("job.cancel") == 2
    assert "job.retry" in actions


# ---------------------------------------------------------------------- library


def test_library_page_and_search(client: TestClient, admin_csrf: str) -> None:
    services = services_of(client)
    album = add_album(services, name="Blue")
    add_track(services, "t1", title="Ocean", album_id=album, size=3 * 1024 * 1024)
    add_track(services, "t2", title=f"Odd {XSS}", needs_review=True)
    page = client.get("/admin/library")
    assert "3.0 MiB" in page.text
    assert ESCAPED in page.text
    assert XSS not in page.text
    found = client.get("/admin/library", params={"q": "blue"})
    assert "Artist Blue \N{EN DASH} Blue" in found.text
    found = client.get("/admin/library", params={"q": "OCEAN"})
    assert "Someone \N{EN DASH} Ocean" in found.text
    assert "Nothing here." in client.get("/admin/library", params={"q": "100%_"}).text


def test_library_page_without_disk_usage(
    client: TestClient, admin_csrf: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken() -> None:
        raise OSError("gone")

    monkeypatch.setattr(services_of(client).library, "usage", broken)
    page = client.get("/admin/library")
    assert page.status_code == 200
    assert "Disk used" not in page.text
    assert '<div class="value bad">?</div>' in page.text


def test_delete_track_removes_rows_file_and_renumbers_playlists(
    client: TestClient, admin_csrf: str, people: People, settings_music: Path
) -> None:
    services = services_of(client)
    for n in range(3):
        write_file(settings_music, f"a/{n}.opus")
        add_track(services, f"t{n}", title=f"Song {n}", path=f"a/{n}.opus")
    now = format_ts(services.clock.now())
    with services.db.transaction() as conn:
        conn.execute(
            "INSERT INTO playlists (id, owner_id, name, created_at, updated_at)"
            " VALUES ('p1', ?, 'P', ?, ?)",
            (people.bob.id, now, now),
        )
        for position in range(3):
            conn.execute(
                "INSERT INTO playlist_tracks (playlist_id, position, track_id, added_at)"
                " VALUES ('p1', ?, ?, ?)",
                (position, f"t{position}", now),
            )
    no_confirm = client.post("/admin/library/tracks/t1/delete", data={"csrf": admin_csrf})
    assert no_confirm.status_code == 400
    r = client.post("/admin/library/tracks/t1/delete", data={"csrf": admin_csrf, "confirm": "yes"})
    assert r.status_code == 303
    assert not (settings_music / "a/1.opus").exists()
    assert (settings_music / "a/0.opus").exists()
    with services.db.read() as conn:
        rows = conn.execute(
            "SELECT position, track_id FROM playlist_tracks ORDER BY position"
        ).fetchall()
        assert [(r["position"], r["track_id"]) for r in rows] == [(0, "t0"), (1, "t2")]
        assert conn.execute("SELECT COUNT(*) AS n FROM tracks WHERE id = 't1'").fetchone()["n"] == 0  # type: ignore[index]
    assert (
        client.post(
            "/admin/library/tracks/t1/delete", data={"csrf": admin_csrf, "confirm": "yes"}
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/admin/library/songs/t0/delete", data={"csrf": admin_csrf, "confirm": "yes"}
        ).status_code
        == 404
    )


def test_delete_never_follows_a_symlink(
    client: TestClient, admin_csrf: str, settings_music: Path, tmp_path: Path
) -> None:
    services = services_of(client)
    outside = tmp_path / "precious.txt"
    outside.write_text("keep me")
    (settings_music / "a").mkdir()
    (settings_music / "a/link.opus").symlink_to(outside)
    add_track(services, "t1", path="a/link.opus")
    r = client.post("/admin/library/tracks/t1/delete", data={"csrf": admin_csrf, "confirm": "yes"})
    assert r.status_code == 303
    assert not (settings_music / "a/link.opus").is_symlink()
    assert outside.read_text() == "keep me"


def count(services: Services, table: str) -> int:
    with services.db.read() as conn:
        row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()  # noqa: S608
    assert row is not None
    n = row["n"]
    assert isinstance(n, int)
    return n


def test_delete_with_an_unsafe_path_keeps_the_delete(
    client: TestClient, admin_csrf: str, caplog: pytest.LogCaptureFixture
) -> None:
    services = services_of(client)
    add_track(services, "t1", path="../escape.opus")
    r = client.post("/admin/library/tracks/t1/delete", data={"csrf": admin_csrf, "confirm": "yes"})
    assert r.headers["location"] == "/admin/library?done=files_left"
    assert count(services, "tracks") == 0
    assert "a file was left on disk (PathRejected)" in caplog.text


def test_album_delete_with_a_failing_middle_unlink(
    client: TestClient,
    admin_csrf: str,
    settings_music: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    services = services_of(client)
    album = add_album(services, name="Gray")
    for n in range(3):
        write_file(settings_music, f"Gray/{n}.opus")
        add_track(services, f"t{n}", album_id=album, path=f"Gray/{n}.opus")
    real = services.library.delete

    def flaky(rel: str) -> None:
        if rel == "Gray/1.opus":
            raise PermissionError(rel)
        real(rel)

    monkeypatch.setattr(services.library, "delete", flaky)
    r = client.post(
        f"/admin/library/albums/{album}/delete", data={"csrf": admin_csrf, "confirm": "yes"}
    )
    assert r.headers["location"] == "/admin/library?done=files_left"
    assert sorted(p.name for p in (settings_music / "Gray").iterdir()) == ["1.opus"]
    assert count(services, "tracks") == 0
    assert count(services, "albums") == 0
    assert "PermissionError" in caplog.text
    assert "files could not be removed" in client.get(r.headers["location"]).text


def test_album_delete_refused_when_a_track_appears(
    client: TestClient, admin_csrf: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The album row goes only while no track points at it (checked by the DELETE itself)."""
    from ultimatetunes.admin.repository import AdminRepository  # noqa: PLC0415

    services = services_of(client)
    album = add_album(services, name="Late")
    add_track(services, "t1", album_id=album)
    real = AdminRepository._delete_track_row

    def and_another(self: AdminRepository, track_id: str) -> None:
        real(self, track_id)
        self.run(
            "INSERT INTO tracks (id, status, title, title_norm, artist_name, album_id,"
            " created_at, updated_at) VALUES ('late', 'pending', 'L', 'l', 'X', ?, 'a', 'a')",
            (album,),
        )

    monkeypatch.setattr(AdminRepository, "_delete_track_row", and_another)
    r = client.post(
        f"/admin/library/albums/{album}/delete", data={"csrf": admin_csrf, "confirm": "yes"}
    )
    assert r.status_code == 409
    assert count(services, "tracks") == 1  # rolled back: t1 is still there


def test_delete_album(client: TestClient, admin_csrf: str, settings_music: Path) -> None:
    services = services_of(client)
    album = add_album(services, name="Red", cover="Red/cover.jpg")
    write_file(settings_music, "Red/cover.jpg")
    for n in range(2):
        write_file(settings_music, f"Red/{n}.opus")
        add_track(services, f"t{n}", album_id=album, path=f"Red/{n}.opus")
    add_track(services, "pending", album_id=album)
    r = client.post(
        f"/admin/library/albums/{album}/delete", data={"csrf": admin_csrf, "confirm": "yes"}
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/library?done=album_deleted"
    assert list((settings_music / "Red").iterdir()) == []
    with services.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM tracks").fetchone()["n"] == 0  # type: ignore[index]
        assert conn.execute("SELECT COUNT(*) AS n FROM albums").fetchone()["n"] == 0  # type: ignore[index]
    entries = client.app.state.admin.auth.recent_audit(5)  # type: ignore[attr-defined]
    assert "album.delete" in [e.action for e in entries]
    assert (
        client.post(
            f"/admin/library/albums/{album}/delete", data={"csrf": admin_csrf, "confirm": "yes"}
        ).status_code
        == 404
    )


def test_delete_refused_while_downloading(client: TestClient, admin_csrf: str) -> None:
    services = services_of(client)
    album = add_album(services, name="Green")
    add_track(services, "t1", album_id=album)
    services.jobs.enqueue(track_id="t1", video_id="aaaaaaaaaaa", priority=30)
    assert services.jobs.claim("w", lease_s=60) is not None
    for path in ("/admin/library/tracks/t1/delete", f"/admin/library/albums/{album}/delete"):
        r = client.post(path, data={"csrf": admin_csrf, "confirm": "yes"})
        assert r.status_code == 409
        assert "in progress" in r.text


# ---------------------------------------------------------------------- yt-dlp


def test_ytdlp_page_and_commands(client: TestClient, admin_csrf: str, clock: FakeClock) -> None:
    services = services_of(client)
    now = format_ts(clock.now())
    with services.db.transaction() as conn:
        conn.execute(
            "INSERT INTO worker_status (worker_id, version, ytdlp_version, last_seen_at)"
            " VALUES ('w1', '0.1', '2026.08.19', ?)",
            (now,),
        )
        conn.execute(
            "INSERT INTO canary_runs (id, source, worker_id, ytdlp_version, ran_at, ok, message)"
            " VALUES ('c1', 'worker', 'w1', '2026.08.19', ?, 0, ?)",
            (now, f"broke {XSS}"),
        )
    page = client.get("/admin/ytdlp")
    assert "2026.08.19" in page.text
    assert ESCAPED in page.text
    assert "not in use (fake catalog)" in page.text
    assert (
        client.post("/admin/ytdlp/update", data={"csrf": admin_csrf})
        .headers["location"]
        .endswith("command_queued")
    )
    assert (
        client.post("/admin/ytdlp/update", data={"csrf": admin_csrf})
        .headers["location"]
        .endswith("command_waiting")
    )
    assert client.post("/admin/ytdlp/canary", data={"csrf": admin_csrf}).status_code == 303
    assert client.post("/admin/ytdlp/reboot", data={"csrf": admin_csrf}).status_code == 404
    with services.db.read() as conn:
        rows = conn.execute("SELECT command FROM worker_commands ORDER BY command").fetchall()
    assert [r["command"] for r in rows] == ["run_canary", "update_ytdlp"]
    assert "waiting" in client.get("/admin/ytdlp").text
    dashboard = client.get("/admin")
    assert "Failed" in dashboard.text


def test_breaker_state_is_shown(
    client: TestClient, admin_csrf: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ultimatetunes.admin import routes  # noqa: PLC0415

    async def open_breaker(_services: object) -> BreakerState:
        return BreakerState(open=True, level=2)

    monkeypatch.setattr(routes, "breaker", open_breaker)
    assert "YouTube Music is throttling" in client.get("/admin").text


# ---------------------------------------------------------------------- audit


def test_audit_page_lists_panel_actions(
    client: TestClient, admin_csrf: str, people: People
) -> None:
    client.post(
        "/admin/users",
        data={"csrf": admin_csrf, "username": "dave", "password": USER_PASSWORD, "role": "user"},
    )
    page = client.get("/admin/audit")
    assert "user.create" in page.text
    assert "admin.login" in page.text
    assert "username=dave" in page.text
    assert "alice" in page.text


def test_human_size() -> None:
    assert human_size(0) == "0 B"
    assert human_size(1536) == "1.5 KiB"
    assert human_size(5 * 1024**4) == "5.0 TiB"
    assert human_size(5 * 1024**5) == "5120.0 TiB"
    assert human_size("x") == "0 B"


def test_page_shows_spanish(client: TestClient, admin_csrf: str) -> None:
    page = client.get("/admin/users", headers={"Accept-Language": "es"})
    assert "Usuarios" in page.text
    assert "Cerrar sesión" in page.text
    assert csrf_of(page.text) == admin_csrf
