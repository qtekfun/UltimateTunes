# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The rest of the web player: Radio, Listen Now shelves, Search sections, downloads,
playlist rename and reorder, Settings (language, theme, password, own API keys) and playlist
imports, each with its access rules (a user never reaches another user's things)."""

import io
import secrets

import pytest
from fastapi.testclient import TestClient

from tests.web.conftest import People, csrf_of, ids, login, make_client
from tests.web.test_pages import HX, songs_of
from ultimatetunes.auth.service import AuthService
from ultimatetunes.core.services import Services
from ultimatetunes.web.security import LANG_COOKIE, SESSION_COOKIE

EXTERNAL = "yt:Fk2Lp9QwXa1"
ALBUM = "ytalbum:MPREb_k3Vd9QmT2xL"


def auth_of(client: TestClient) -> AuthService:
    found: AuthService = client.app.state.web.auth  # type: ignore[attr-defined]
    return found


# ---------------------------------------------------------------------- Listen Now and Radio


def test_listen_now_shows_most_played_and_stations(
    client: TestClient, ana: str, services: Services
) -> None:
    track = ids(services)["Brasas"]
    headers = {"X-CSRF-Token": ana}
    client.post("/web/api/scrobble", data={"id": track}, headers=headers)
    client.post("/web/star", data={"kind": "song", "id": track, "on": "1"}, headers=headers)
    page = client.get("/")
    assert "Most played" in page.text
    assert "Your stations" in page.text
    assert f'data-act="seed-radio" data-id="{track}"' in page.text


def test_radio_page(client: TestClient, ana: str, services: Services) -> None:
    empty = client.get("/web/radio")
    assert empty.status_code == 200
    assert "a station for each one appears here" in empty.text
    assert f'data-act="artist-radio" data-id="{ids(services)["Marisol Vega"]}"' in empty.text
    track = ids(services)["Tidewater"]
    client.post(
        "/web/star", data={"kind": "song", "id": track, "on": "1"}, headers={"X-CSRF-Token": ana}
    )
    assert "Tidewater Radio" in client.get("/web/radio").text


def test_search_has_library_and_youtube_music_sections(client: TestClient, ana: str) -> None:
    r = client.get("/web/search", params={"q": "lanterns"})
    library, youtube = r.text.split('id="h-yt"', 1)
    assert "In your library" in library
    assert "Lighthouse Keeper" in library
    assert "Low Tide Letters" in youtube
    assert 'data-state="not_requested"' in youtube


# ---------------------------------------------------------------------- downloads


def test_download_a_song_and_follow_its_state(
    client: TestClient, ana: str, services: Services
) -> None:
    r = client.post(f"/web/api/request/{EXTERNAL}", headers={"X-CSRF-Token": ana})
    assert r.status_code == 202
    assert r.json()["state"] == "queued"
    states = client.get("/web/api/states", params=[("id", EXTERNAL), ("id", "yt:Rb8Tn3ZcYv0")])
    assert states.status_code == 200
    assert states.json() == {
        EXTERNAL: {"state": "queued", "progress": 0.0},
        "yt:Rb8Tn3ZcYv0": {"state": "not_requested", "progress": 0.0},
    }
    album = client.get(f"/web/album/{ALBUM}")
    assert 'data-state="queued"' in album.text
    again = client.post(f"/web/api/request/{EXTERNAL}", headers={"X-CSRF-Token": ana})
    assert again.json()["state"] == "queued"
    ready = client.post(
        f"/web/api/request/{ids(services)['Tidewater']}", headers={"X-CSRF-Token": ana}
    )
    assert ready.status_code == 200
    assert ready.json()["state"] == "ready"


def test_download_needs_csrf_and_a_song(client: TestClient, ana: str) -> None:
    assert client.post(f"/web/api/request/{EXTERNAL}").status_code == 403
    r = client.post(f"/web/api/request/{ALBUM}", headers={"X-CSRF-Token": ana})
    assert r.status_code == 400


@pytest.mark.parametrize(
    "params",
    [[("id", ALBUM)], [("id", "yt:" + "x" * 90)], [("id", f"yt:{i:011d}") for i in range(61)]],
)
def test_bad_state_requests(client: TestClient, ana: str, params: list[tuple[str, str]]) -> None:
    assert client.get("/web/api/states", params=params).status_code == 400


# ---------------------------------------------------------------------- playlists


def _playlist(client: TestClient, csrf: str, name: str, *songs: str) -> str:
    r = client.post("/web/playlists", data={"csrf": csrf, "name": name, "song": songs[0]})
    playlist = str(r.headers["location"].rsplit("/", 1)[1])
    for song in songs[1:]:
        client.post(f"/web/playlists/{playlist}/add", data={"csrf": csrf, "song": song})
    return playlist


def test_rename_and_reorder_a_playlist(client: TestClient, ana: str, services: Services) -> None:
    known = ids(services)
    playlist = _playlist(client, ana, "Mix", known["Tidewater"], known["Brasas"], EXTERNAL)
    r = client.post(f"/web/playlists/{playlist}/rename", data={"csrf": ana, "name": "Road mix"})
    assert r.status_code == 303
    page = client.get(f"/web/playlist/{playlist}")
    assert "Road mix" in page.text
    assert "Move down" in page.text
    r = client.post(f"/web/playlists/{playlist}/move", data={"csrf": ana, "index": "2", "to": "0"})
    assert r.status_code == 303
    order = [s["title"] for s in songs_of(client.get(f"/web/playlist/{playlist}").text)]
    assert order == ["Low Tide Letters", "Tidewater", "Brasas"]
    hx = client.post(
        f"/web/playlists/{playlist}/move", data={"csrf": ana, "index": "0", "to": "1"}, headers=HX
    )
    assert hx.status_code == 200
    assert "hx-location" in hx.headers
    order = [s["title"] for s in songs_of(client.get(f"/web/playlist/{playlist}").text)]
    assert order == ["Tidewater", "Low Tide Letters", "Brasas"]


@pytest.mark.parametrize("form", [{"index": "5", "to": "0"}, {"index": "x", "to": "0"}])
def test_bad_moves(client: TestClient, ana: str, services: Services, form: dict[str, str]) -> None:
    playlist = _playlist(client, ana, "Two", ids(services)["Tidewater"])
    r = client.post(f"/web/playlists/{playlist}/move", data={"csrf": ana, **form})
    assert r.status_code == 400
    assert "Something went wrong" in r.text


def test_others_cannot_rename_or_reorder(
    app_factory: object, people: People, services: Services
) -> None:
    track = ids(services)["Tidewater"]
    with make_client(app_factory) as ana, make_client(app_factory) as bob:
        ana_csrf = login(ana, people.ana)
        bob_csrf = login(bob, people.bob)
        playlist = _playlist(ana, ana_csrf, "Private", track, ids(services)["Brasas"])
        for action, form in (("rename", {"name": "Mine"}), ("move", {"index": "0", "to": "1"})):
            r = bob.post(f"/web/playlists/{playlist}/{action}", data={"csrf": bob_csrf, **form})
            assert r.status_code == 404, action
        page = ana.get(f"/web/playlist/{playlist}")
        assert "Private" in page.text
        assert [s["title"] for s in songs_of(page.text)] == ["Tidewater", "Brasas"]


# ---------------------------------------------------------------------- settings


def test_settings_page(client: TestClient, ana: str) -> None:
    r = client.get("/web/settings")
    assert r.status_code == 200
    for text in ("Appearance", 'data-act="theme"', "Change password", "Keyboard shortcuts"):
        assert text in r.text
    assert "No API keys." in r.text


def test_language_choice_overrides_the_browser(client: TestClient, ana: str) -> None:
    r = client.post("/web/settings/language", data={"csrf": ana, "lang": "es"})
    assert r.status_code == 303
    assert r.headers["location"] == "/web/settings?done=language"
    cookie = r.headers["set-cookie"].lower()
    assert cookie.startswith(LANG_COOKIE)
    assert "samesite=strict" in cookie
    assert "Biblioteca" in client.get("/web/library", headers={"Accept-Language": "en"}).text
    assert "Idioma guardado." in client.get("/web/settings?done=language").text
    client.post("/web/settings/language", data={"csrf": ana, "lang": "en"})
    assert "Library" in client.get("/web/library", headers={"Accept-Language": "es"}).text
    hx = client.post("/web/settings/language", data={"csrf": ana, "lang": "auto"}, headers=HX)
    assert hx.headers["hx-redirect"] == "/web/settings?done=language"
    assert "Biblioteca" in client.get("/web/library", headers={"Accept-Language": "es"}).text
    bad = client.post("/web/settings/language", data={"csrf": ana, "lang": "fr"})
    assert bad.status_code == 400


def test_change_password(app_factory: object, people: People) -> None:
    new = secrets.token_urlsafe(18)
    with make_client(app_factory) as laptop, make_client(app_factory) as phone:
        csrf = login(laptop, people.ana)
        login(phone, people.ana)
        wrong = laptop.post(
            "/web/settings/password",
            data={"csrf": csrf, "current": secrets.token_urlsafe(12), "new": new, "confirm": new},
        )
        assert wrong.status_code == 400
        assert "The current password is wrong." in wrong.text
        mismatch = laptop.post(
            "/web/settings/password",
            data={"csrf": csrf, "current": people.ana.password, "new": new, "confirm": new + "x"},
        )
        assert mismatch.status_code == 400
        short = laptop.post(
            "/web/settings/password",
            data={"csrf": csrf, "current": people.ana.password, "new": "short", "confirm": "short"},
        )
        assert short.status_code == 400
        assert "12 to 1024" in short.text
        r = laptop.post(
            "/web/settings/password",
            data={"csrf": csrf, "current": people.ana.password, "new": new, "confirm": new},
        )
        assert r.status_code == 303
        assert SESSION_COOKIE in r.headers["set-cookie"]
        # This browser stays signed in with a new session; the other one is signed out.
        assert laptop.get("/web/settings").status_code == 200
        assert phone.get("/web/settings").status_code == 303
        with make_client(app_factory) as fresh:
            form = fresh.get("/")
            ok = fresh.post(
                "/web/login",
                data={"csrf": csrf_of(form.text), "username": "ana", "password": new},
            )
            assert ok.status_code == 303


def test_own_api_keys_are_listed_and_revoked(app_factory: object, people: People) -> None:
    with make_client(app_factory) as ana, make_client(app_factory) as bob:
        ana_csrf = login(ana, people.ana)
        bob_csrf = login(bob, people.bob)
        auth = auth_of(ana)
        created = auth.create_key(people.ana.user.id, "Pixel phone", actor=None)
        ana_key, secret = created.key, created.secret
        bob_key = auth.create_key(people.bob.user.id, "Bob tablet", actor=None).key
        page = ana.get("/web/settings")
        assert "Pixel phone" in page.text
        assert "Bob tablet" not in page.text
        assert secret not in page.text
        # IDOR: bob cannot revoke ana's key, ana cannot revoke bob's.
        r = bob.post(f"/web/settings/keys/{ana_key.id}/revoke", data={"csrf": bob_csrf})
        assert r.status_code == 404
        r = ana.post(f"/web/settings/keys/{bob_key.id}/revoke", data={"csrf": ana_csrf})
        assert r.status_code == 404
        r = ana.post(f"/web/settings/keys/{ana_key.id}/revoke", data={"csrf": ana_csrf})
        assert r.status_code == 303
        assert "Pixel phone" not in ana.get("/web/settings").text
        assert all(k.revoked_at is None for k in auth.list_keys(people.bob.user.id))


# ---------------------------------------------------------------------- imports


def test_import_page_and_url_import(client: TestClient, ana: str) -> None:
    page = client.get("/web/imports")
    assert page.status_code == 200
    assert "No imports yet." in page.text
    r = client.post(
        "/web/imports/url",
        data={
            "csrf": ana,
            "url": "https://music.youtube.com/playlist?list=PLfake0000000000000001",
            "name": "Morning",
        },
    )
    assert r.status_code == 303, r.text
    detail = r.headers["location"]
    assert detail.startswith("/web/imports/")
    shown = client.get(detail)
    assert shown.status_code == 200
    assert "Morning" in shown.text
    assert "Morning" in client.get("/web/imports").text


def test_url_imports_are_checked(client: TestClient, ana: str) -> None:
    r = client.post(
        "/web/imports/url", data={"csrf": ana, "url": "https://example.com/playlist?list=PL1"}
    )
    assert r.status_code == 400
    assert client.post("/web/imports/url", data={"url": "x"}).status_code == 403


def test_file_import(client: TestClient, ana: str) -> None:
    csv = b"title,artist\nLow Tide Letters,The Paper Lanterns\n"
    files = {"file": ("mix.csv", io.BytesIO(csv), "text/csv")}
    form = {"format": "csv", "name": "From a file"}
    refused = client.post("/web/imports/file", files=files, data=form)
    assert refused.status_code == 403
    files = {"file": ("mix.csv", io.BytesIO(csv), "text/csv")}
    r = client.post(
        "/web/imports/file", files=files, data=form, headers={"X-CSRF-Token": ana, **HX}
    )
    assert r.status_code == 200, r.text
    assert '"path": "/web/imports/' in r.headers["hx-location"]
    assert "From a file" in client.get("/web/imports").text
    bad = client.post(
        "/web/imports/file",
        files={"file": ("x.csv", io.BytesIO(b"x"), "text/csv")},
        data={"format": "nope"},
        headers={"X-CSRF-Token": ana},
    )
    assert bad.status_code == 400


def test_imports_belong_to_their_user(app_factory: object, people: People) -> None:
    with make_client(app_factory) as ana, make_client(app_factory) as bob:
        ana_csrf = login(ana, people.ana)
        login(bob, people.bob)
        r = ana.post(
            "/web/imports/url",
            data={
                "csrf": ana_csrf,
                "url": "https://music.youtube.com/playlist?list=PLfake0000000000000002",
                "name": "Ana only",
            },
        )
        detail = r.headers["location"]
        assert bob.get(detail).status_code == 404
        assert "Ana only" not in bob.get("/web/imports").text
        assert bob.get("/web/imports/not-a-uuid").status_code == 404


def test_password_change_reloads_the_page_with_the_new_token(
    client: TestClient, people: People
) -> None:
    csrf = login(client, people.ana)
    new = secrets.token_urlsafe(18)
    r = client.post(
        "/web/settings/password",
        data={"csrf": csrf, "current": people.ana.password, "new": new, "confirm": new},
        headers=HX,
    )
    assert r.status_code == 200
    # A full reload (not a swap of #content): the page gets the new session's token.
    assert r.headers["hx-redirect"] == "/web/settings?done=password"
    page = client.get("/web/settings?done=password")
    fresh = csrf_of(page.text)
    assert fresh != csrf
    star = {"kind": "song", "id": EXTERNAL, "on": "0"}
    assert client.post("/web/star", data=star, headers={"X-CSRF-Token": fresh}).status_code == 200
    assert client.post("/web/star", data=star, headers={"X-CSRF-Token": csrf}).status_code == 403


def test_a_refused_form_shows_a_page_to_reload(client: TestClient, ana: str) -> None:
    r = client.post("/web/playlists", data={"csrf": "stale", "name": "x"}, headers=HX)
    assert r.status_code == 403
    assert r.headers["content-type"].startswith("text/html")
    assert "The form expired" in r.text
    assert 'hx-boost="false"' in r.text
    assert "<audio" not in r.text
    full = client.post("/web/playlists", data={"csrf": "stale", "name": "x"})
    assert full.status_code == 403
    assert "<audio" in full.text


def test_file_import_without_javascript(client: TestClient, ana: str) -> None:
    csv = b"title,artist\nLow Tide Letters,The Paper Lanterns\n"
    files = {"file": ("mix.csv", io.BytesIO(csv), "text/csv")}
    r = client.post(
        "/web/imports/file", files=files, data={"format": "csv", "name": "No JS", "csrf": ana}
    )
    assert r.status_code == 303, r.text
    assert "No JS" in client.get("/web/imports").text
    files = {"file": ("mix.csv", io.BytesIO(csv), "text/csv")}
    wrong = client.post("/web/imports/file", files=files, data={"format": "csv", "csrf": "x"})
    assert wrong.status_code == 403
    garbage = client.post(
        "/web/imports/file",
        content=b"not multipart",
        headers={"Content-Type": "multipart/form-data; boundary=x"},
    )
    assert garbage.status_code == 403
