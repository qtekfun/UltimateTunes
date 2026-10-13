# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the player and the actions do: media through the session, the player's JSON calls,
stars and playlists, and that one user never reaches another user's private things."""

import hashlib
import re
from importlib import resources
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.web.conftest import People, ids, login, make_client
from tests.web.test_pages import songs_of
from ultimatetunes.core.services import Services
from ultimatetunes.web import routes
from ultimatetunes.web.catalog_es import ES
from ultimatetunes.web.i18n import translator

PACKAGE = Path(str(resources.files("ultimatetunes")))
TEMPLATES = PACKAGE / "templates" / "web"
_MESSAGE = re.compile(r'_\("((?:[^"\\]|\\.)*)"')
HX = {"HX-Request": "true"}
EXTERNAL = "yt:Fk2Lp9QwXa1"


# ---------------------------------------------------------------------- media


def test_stream_with_range_through_the_session(
    client: TestClient, ana: str, services: Services
) -> None:
    track = ids(services)["Tidewater"]
    full = client.get(f"/web/stream/{track}")
    assert full.status_code == 200
    assert full.headers["accept-ranges"] == "bytes"
    part = client.get(f"/web/stream/{track}", headers={"Range": "bytes=0-9"})
    assert part.status_code == 206
    assert part.content == full.content[:10]
    assert part.headers["content-range"].startswith("bytes 0-9/")
    head = client.head(f"/web/stream/{track}")
    assert head.status_code == 200
    assert head.content == b""
    assert head.headers["content-length"] == str(len(full.content))


def test_head_of_an_external_song_starts_nothing(
    client: TestClient, ana: str, services: Services
) -> None:
    r = client.head(f"/web/stream/{EXTERNAL}")
    assert r.status_code == 200
    assert r.content == b""
    with services.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM jobs").scalar() == 0


def test_head_of_a_pending_library_song_starts_nothing(
    client: TestClient, ana: str, services: Services
) -> None:
    """Audit I6: a HEAD never queues a download, for a `yt:` id or a pending track (starred,
    say) alike; only a GET does."""
    pending = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01c0aa"
    with services.db.transaction() as conn:
        conn.execute(
            "INSERT INTO tracks (id, status, title, title_norm, artist_name, yt_video_id,"
            " created_at, updated_at) VALUES (?, 'pending', 'P', 'p', 'A', 'Fk2Lp9QwXa2',"
            " '2026-10-12T08:00:00.000Z', '2026-10-12T08:00:00.000Z')",
            (pending,),
        )
    for _ in range(3):
        r = client.head(f"/web/stream/{pending}")
        assert r.status_code == 200
        assert r.content == b""
        assert r.headers["cache-control"] == "no-store"
    with services.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM jobs").scalar() == 0


def test_stream_of_an_unknown_song(client: TestClient, ana: str) -> None:
    r = client.get("/web/stream/0199d6a2-4c1e-7b3a-9f10-2a6c8e01ffff")
    assert r.status_code == 404
    assert r.json()["error"] == "not_found"


def test_covers_through_the_session(client: TestClient, ana: str, services: Services) -> None:
    album = ids(services)["Harbour Lights"]
    r = client.get(f"/web/cover/al-{album}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/")
    assert r.headers["cache-control"] == "private, max-age=86400"


# ---------------------------------------------------------------------- player calls


def test_first_play_status(client: TestClient, ana: str, services: Services) -> None:
    r = client.get(f"/web/api/status/{EXTERNAL}")
    assert r.status_code == 200
    assert r.json()["state"] == "not_requested"
    ready = client.get(f"/web/api/status/{ids(services)['Tidewater']}")
    assert ready.json()["state"] == "ready"
    album = client.get(f"/web/api/status/ytalbum:{'MPREb_k3Vd9QmT2xL'}")
    assert album.status_code == 400


def test_radio_from_a_song_and_from_an_artist(client: TestClient, ana: str) -> None:
    r = client.get(f"/web/api/radio/{EXTERNAL}")
    assert r.status_code == 200
    songs = r.json()["songs"]
    assert songs
    assert all({"id", "title", "artist", "cover"} <= s.keys() for s in songs)
    assert EXTERNAL not in [s["id"] for s in songs]
    artist = client.get("/web/api/radio/ytartist:UCq8XbV1r0LwZ5mN3tYp7kQe")
    assert artist.status_code == 200
    assert artist.json()["songs"]


def test_lyrics(client: TestClient, ana: str, services: Services) -> None:
    r = client.get(f"/web/api/lyrics/{ids(services)['Tidewater']}")
    assert r.status_code == 200
    body = r.json()
    assert body["synced"] is True
    assert body["lines"][0] == {"start": 0, "text": "Tidewater, first line"}
    assert client.get(f"/web/api/lyrics/{EXTERNAL}").json() == {"synced": False, "lines": []}


def test_scrobbles_count_for_listen_now(client: TestClient, ana: str, services: Services) -> None:
    track = ids(services)["Brasas"]
    now = client.post(
        "/web/api/scrobble",
        data={"id": track, "submission": "false"},
        headers={"X-CSRF-Token": ana},
    )
    assert now.status_code == 204
    played = client.post("/web/api/scrobble", data={"id": track}, headers={"X-CSRF-Token": ana})
    assert played.status_code == 204
    page = client.get("/web")
    recent = page.text.split("Recently played", 1)[1].split("Recently added", 1)[0]
    assert "Salt &amp; Ember" in recent
    missing = client.post("/web/api/scrobble", data={}, headers={"X-CSRF-Token": ana})
    assert missing.status_code == 400


# ---------------------------------------------------------------------- stars


def test_star_and_unstar(client: TestClient, ana: str, services: Services) -> None:
    track = ids(services)["Lighthouse Keeper"]
    album = ids(services)["Harbour Lights"]
    artist = ids(services)["Marisol Vega"]
    for kind, item in (("song", track), ("album", album), ("artist", artist)):
        r = client.post(
            "/web/star", data={"kind": kind, "id": item, "on": "1"}, headers={"X-CSRF-Token": ana}
        )
        assert r.status_code == 200
        assert 'class="star on"' in r.text
        assert '"on": "0"' in r.text
    favourites = client.get("/web/library/favourites")
    assert [s["title"] for s in songs_of(favourites.text)] == ["Lighthouse Keeper"]
    assert "Harbour Lights" in favourites.text
    assert "Marisol Vega" in favourites.text
    r = client.post(
        "/web/star", data={"kind": "song", "id": track, "on": "0"}, headers={"X-CSRF-Token": ana}
    )
    assert 'class="star"' in r.text
    assert songs_of(client.get("/web/library/favourites").text) == []


@pytest.mark.parametrize(
    "form",
    [
        {"kind": "playlist", "id": "x", "on": "1"},
        {"kind": "song", "id": "", "on": "1"},
        {"kind": "song", "id": "y" * 81, "on": "1"},
        {"kind": "album", "id": "ytalbum:MPREb_k3Vd9QmT2xL", "on": "1"},
    ],
)
def test_bad_star_requests(client: TestClient, ana: str, form: dict[str, str]) -> None:
    r = client.post("/web/star", data=form, headers={"X-CSRF-Token": ana})
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_parameter"


# ---------------------------------------------------------------------- playlists


def _new_playlist(client: TestClient, csrf: str, name: str, song: str | None = None) -> str:
    data = {"csrf": csrf, "name": name, **({"song": song} if song else {})}
    r = client.post("/web/playlists", data=data)
    assert r.status_code == 303, r.text
    location = r.headers["location"]
    assert location.startswith("/web/playlist/")
    return str(location.rsplit("/", 1)[1])


def test_playlist_lifecycle(client: TestClient, ana: str, services: Services) -> None:
    tidewater, brasas = ids(services)["Tidewater"], ids(services)["Brasas"]
    playlist = _new_playlist(client, ana, "Road trip", tidewater)
    add_page = client.get(f"/web/add/{brasas}")
    assert add_page.status_code == 200
    assert "Road trip" in add_page.text
    added = client.post(
        f"/web/playlists/{playlist}/add", data={"csrf": ana, "song": brasas}, headers=HX
    )
    assert added.status_code == 200
    assert '"path": "/web/playlist/' in added.headers["hx-location"]
    page = client.get(f"/web/playlist/{playlist}")
    assert [s["title"] for s in songs_of(page.text)] == ["Tidewater", "Brasas"]
    assert "Remove from this playlist" in page.text
    assert "Delete playlist" in page.text
    removed = client.post(f"/web/playlists/{playlist}/remove", data={"csrf": ana, "index": "0"})
    assert removed.status_code == 303
    assert [s["title"] for s in songs_of(client.get(f"/web/playlist/{playlist}").text)] == [
        "Brasas"
    ]
    assert "Road trip" in client.get("/web/library/playlists").text
    deleted = client.post(f"/web/playlists/{playlist}/delete", data={"csrf": ana})
    assert deleted.status_code == 303
    assert deleted.headers["location"] == "/web/library/playlists"
    assert client.get(f"/web/playlist/{playlist}").status_code == 404


def test_external_songs_can_be_added(client: TestClient, ana: str) -> None:
    playlist = _new_playlist(client, ana, "Discoveries", EXTERNAL)
    songs = songs_of(client.get(f"/web/playlist/{playlist}").text)
    assert [s["title"] for s in songs] == ["Low Tide Letters"]


def test_playlist_form_errors(client: TestClient, ana: str) -> None:
    assert client.post("/web/playlists", data={"csrf": ana, "name": " "}).status_code == 400
    too_long = client.post("/web/playlists", data={"csrf": ana, "name": "n" * 201})
    assert too_long.status_code == 400
    playlist = _new_playlist(client, ana, "Empty")
    no_song = client.post(f"/web/playlists/{playlist}/add", data={"csrf": ana})
    assert no_song.status_code == 400
    assert "This playlist is empty" in client.get(f"/web/playlist/{playlist}").text
    assert client.get("/web/add/ytalbum:MPREb_k3Vd9QmT2xL").status_code == 400


def test_one_user_never_reaches_another_users_things(
    app_factory: object, people: People, services: Services
) -> None:
    """IDOR: bob guesses ana's private playlist id and her stars."""
    track = ids(services)["Tidewater"]
    with make_client(app_factory) as ana, make_client(app_factory) as bob:
        ana_csrf = login(ana, people.ana)
        bob_csrf = login(bob, people.bob)
        playlist = _new_playlist(ana, ana_csrf, "Ana only", track)
        ana.post("/web/star", data={"kind": "song", "id": track, "on": "1", "csrf": ana_csrf})

        assert bob.get(f"/web/playlist/{playlist}").status_code == 404
        assert "Ana only" not in bob.get("/web/library/playlists").text
        assert "Ana only" not in bob.get(f"/web/add/{track}").text
        for action, data in (
            ("add", {"song": track}),
            ("remove", {"index": "0"}),
            ("delete", {}),
        ):
            r = bob.post(f"/web/playlists/{playlist}/{action}", data={"csrf": bob_csrf, **data})
            assert r.status_code == 404, action
        assert songs_of(bob.get("/web/library/favourites").text) == []
        # Unstarring as bob leaves ana's star alone.
        bob.post("/web/star", data={"kind": "song", "id": track, "on": "0", "csrf": bob_csrf})
        assert [s["title"] for s in songs_of(ana.get(f"/web/playlist/{playlist}").text)] == [
            "Tidewater"
        ]
        assert songs_of(ana.get("/web/library/favourites").text)[0]["starred"] is True
        # Bob's own CSRF token never works with ana's session.
        r = ana.post("/web/star", data={"kind": "song", "id": track, "on": "0", "csrf": bob_csrf})
        assert r.status_code == 403


def test_a_public_playlist_is_read_only_for_others(
    app_factory: object, people: People, services: Services
) -> None:
    track = ids(services)["Tidewater"]
    with make_client(app_factory) as ana, make_client(app_factory) as bob:
        ana_csrf = login(ana, people.ana)
        bob_csrf = login(bob, people.bob)
        playlist = _new_playlist(ana, ana_csrf, "Shared mix", track)
        with services.db.transaction() as conn:
            conn.execute("UPDATE playlists SET is_public = 1 WHERE id = ?", (playlist,))
        page = bob.get(f"/web/playlist/{playlist}")
        assert page.status_code == 200
        assert "Delete playlist" not in page.text
        assert "Remove from this playlist" not in page.text
        r = bob.post(f"/web/playlists/{playlist}/delete", data={"csrf": bob_csrf})
        assert r.status_code == 403


# ---------------------------------------------------------------------- static, templates, i18n


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("web.css", "text/css"),
        ("player.js", "text/javascript"),
        ("htmx.min.js", "text/javascript"),
        ("icon.svg", "image/svg+xml"),
        ("blank.svg", "image/svg+xml"),
    ],
)
def test_static_files(client: TestClient, name: str, kind: str) -> None:
    r = client.get(f"/web/static/{name}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(kind)


def test_the_logo_is_the_apps_launcher_icon() -> None:
    """icon.svg is the launcher icon drawn from the same vector drawables: note, tile, light."""
    res = Path(__file__).resolve().parents[3] / "android" / "app" / "src" / "main" / "res"
    foreground = (res / "drawable" / "ic_launcher_foreground.xml").read_text(encoding="utf-8")
    background = (res / "drawable" / "ic_launcher_background.xml").read_text(encoding="utf-8")
    logo = (PACKAGE / "static" / "web" / "icon.svg").read_text(encoding="utf-8")
    note = re.search(r'android:pathData="([^"]+)"', foreground)
    assert note is not None
    assert f'd="{note.group(1)}"' in logo
    for colour in re.findall(r'(?:start|end)Color="#FF([0-9A-F]{6})"', background):
        assert f'stop-color="#{colour}"' in logo
    assert "translate(28.5 30.1) scale(2)" in logo
    assert 'viewBox="18 18 72 72"' in logo
    assert "http" not in logo.replace("http://www.w3.org/2000/svg", "")


def test_unknown_static_files(client: TestClient) -> None:
    assert client.get("/web/static/../settings.py").status_code == 404
    assert client.get("/web/static/admin.css").status_code == 404


def test_htmx_is_the_panels_vendored_copy(client: TestClient) -> None:
    record = (PACKAGE / "static" / "admin" / "htmx.min.js.license").read_text(encoding="utf-8")
    digest = hashlib.sha256(client.get("/web/static/htmx.min.js").content).hexdigest()
    assert f"SHA-256: {digest}" in record


def test_pages_load_nothing_from_other_hosts_and_run_no_inline_script() -> None:
    for template in TEMPLATES.glob("*.html"):
        text = template.read_text(encoding="utf-8")
        assert "http://" not in text, template.name
        assert "https://" not in text, template.name
        assert "<script>" not in text, template.name
        assert " on" + "click=" not in text, template.name
        assert "style=" not in text, template.name
        assert "/admin" not in text, template.name  # the panel is never advertised
        for src in re.findall(r'<script src="([^"]+)"', text):
            assert src.startswith("/web/static/"), template.name
    player = (PACKAGE / "static" / "web" / "player.js").read_text(encoding="utf-8")
    assert ".innerHTML" not in player
    assert "eval(" not in player
    assert "apiKey" not in player
    assert 'localStorage.setItem("ut.volume"' in player


def test_templates_autoescape() -> None:
    env = routes.Templates().env
    assert env.autoescape is True
    assert env.from_string("{{ x }}").render(x="<b>") == "&lt;b&gt;"


def test_every_message_has_a_spanish_translation() -> None:
    messages: set[str] = set()
    for template in TEMPLATES.glob("*.html"):
        messages |= set(_MESSAGE.findall(template.read_text(encoding="utf-8")))
    messages |= set(routes.MESSAGES.values()) | {label for _href, label in routes.LIBRARY_TABS}
    missing = sorted(m for m in messages if m not in ES)
    assert not missing
    for english, spanish in ES.items():
        assert re.findall(r"%\(\w+\)s", english) == re.findall(r"%\(\w+\)s", spanish)


def test_translator() -> None:
    assert translator("es")("%(count)s songs", count=3) == "3 canciones"
    assert translator("en")("%(count)s songs", count=3) == "3 songs"
    assert translator("es")("Not in the catalog") == "Not in the catalog"


def test_spanish_pages_and_errors(client: TestClient, ana: str) -> None:
    es = {"Accept-Language": "es"}
    assert "Biblioteca" in client.get("/web/library", headers=es).text
    r = client.post("/web/star", data={"kind": "song", "id": "x"}, headers=es)
    assert r.status_code == 403
    assert "formulario" in r.json()["message"]


@pytest.mark.parametrize(
    ("seconds", "text"), [(0, "0:00"), (65, "1:05"), (3725, "1:02:05"), ("x", "0:00")]
)
def test_duration_filter(seconds: object, text: str) -> None:
    assert routes.duration(seconds) == text


def test_catalog_lookups_are_charged_to_the_signed_in_user(
    client: TestClient, ana: str, services: Services, people: People
) -> None:
    from ultimatetunes.core.caller import current_bucket  # noqa: PLC0415
    from ultimatetunes.search.catalog import CatalogTrack  # noqa: PLC0415

    seen: list[str | None] = []
    catalog = services.catalog
    original = catalog.search_songs

    async def spy(query: str, limit: int) -> list[CatalogTrack]:
        seen.append(current_bucket())
        result: list[CatalogTrack] = await original(query, limit)
        return result

    catalog.search_songs = spy  # type: ignore[method-assign]
    assert client.get("/web/search", params={"q": "harbor"}).status_code == 200
    assert seen
    assert set(seen) == {people.ana.user.id}
