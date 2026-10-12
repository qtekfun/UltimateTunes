# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The pages of the web player: full loads, HTMX partials, data from the library and the fake
catalog, escaping and languages."""

import json
import re
from html import unescape

import pytest
from fastapi.testclient import TestClient

from tests.web.conftest import ids
from ultimatetunes.core.services import Services

HX = {"HX-Request": "true"}
_SONG = re.compile(r"data-song='([^']+)'")


def songs_of(html: str) -> list[dict[str, object]]:
    return [json.loads(unescape(m)) for m in _SONG.findall(html)]


def test_listen_now_full_page_has_the_shell_and_the_player(client: TestClient, ana: str) -> None:
    r = client.get("/web")
    assert r.status_code == 200
    assert "<audio" in r.text
    assert 'id="content"' in r.text
    assert "Harbour Lights" in r.text
    assert "Salt &amp; Ember" in r.text
    assert r.headers["vary"] == "HX-Request"


def test_htmx_navigation_gets_only_the_content(client: TestClient, ana: str) -> None:
    r = client.get("/web/library", headers=HX)
    assert r.status_code == 200
    assert "<audio" not in r.text
    assert "<html" not in r.text
    assert r.text.lstrip().startswith("<title>")
    assert "Harbour Lights" in r.text


def test_slash_redirects(client: TestClient, ana: str) -> None:
    r = client.get("/web/")
    assert r.status_code == 308
    assert r.headers["location"] == "/"


def test_library_tabs(client: TestClient, ana: str, services: Services) -> None:
    artists = client.get("/web/library/artists")
    assert artists.status_code == 200
    assert "The Paper Lanterns" in artists.text
    assert "Marisol Vega" in artists.text
    assert client.get("/web/library/playlists").status_code == 200
    favourites = client.get("/web/library/favourites")
    assert favourites.status_code == 200
    assert "Nothing in your favourites yet" in favourites.text
    paged = client.get("/web/library", params={"offset": 60})
    assert paged.status_code == 200
    assert "No albums yet." in paged.text
    assert client.get("/web/library", params={"offset": -1}).status_code == 400


def test_album_page_lists_playable_songs(client: TestClient, ana: str, services: Services) -> None:
    album = ids(services)["Harbour Lights"]
    r = client.get(f"/web/album/{album}")
    assert r.status_code == 200
    songs = songs_of(r.text)
    assert [s["title"] for s in songs] == ["Lighthouse Keeper", "Tidewater"]
    assert songs[0]["external"] is False
    assert songs[0]["albumId"] == album
    assert f'src="/web/cover/al-{album}"' in r.text


def test_artist_page(client: TestClient, ana: str, services: Services) -> None:
    artist = ids(services)["Marisol Vega"]
    r = client.get(f"/web/artist/{artist}")
    assert r.status_code == 200
    assert "Salt &amp; Ember" in r.text
    assert 'data-act="artist-radio"' in r.text


def test_external_album_and_artist_pages(client: TestClient, ana: str) -> None:
    album = client.get("/web/album/ytalbum:MPREb_k3Vd9QmT2xL")
    assert album.status_code == 200
    songs = songs_of(album.text)
    assert songs[0]["id"] == "yt:Fk2Lp9QwXa1"
    assert songs[0]["external"] is True
    assert "Not in your library yet" in album.text
    artist = client.get("/web/artist/ytartist:UCq8XbV1r0LwZ5mN3tYp7kQe")
    assert artist.status_code == 200
    assert "Lanterns at Dusk" in artist.text


def test_search_merges_library_and_catalog(client: TestClient, ana: str) -> None:
    empty = client.get("/web/search")
    assert empty.status_code == 200
    assert "Search your library" in empty.text
    r = client.get("/web/search", params={"q": "lanterns"})
    assert r.status_code == 200
    found = songs_of(r.text)
    assert any(s["external"] for s in found)
    assert "The Paper Lanterns" in r.text
    long = client.get("/web/search", params={"q": "x" * 201})
    assert long.status_code == 400


def test_missing_items_show_the_error_page(client: TestClient, ana: str) -> None:
    r = client.get("/web/album/0199d6a2-4c1e-7b3a-9f10-2a6c8e01ffff")
    assert r.status_code == 404
    assert "Something went wrong" in r.text
    assert "<audio" in r.text
    partial = client.get("/web/playlist/0199d6a2-4c1e-7b3a-9f10-2a6c8e01ffff", headers=HX)
    assert partial.status_code == 404
    assert "<audio" not in partial.text


def test_text_from_the_library_is_escaped(client: TestClient, ana: str, services: Services) -> None:
    with services.db.transaction() as conn:
        conn.execute(
            "UPDATE albums SET name = ? WHERE id = ?",
            ("<script>alert(1)</script>", ids(services)["Harbour Lights"]),
        )
        conn.execute("UPDATE tracks SET title = ? WHERE title = 'Tidewater'", ("it's <b>bold</b>",))
    r = client.get(f"/web/album/{ids(services)['<script>alert(1)</script>']}")
    assert r.status_code == 200
    assert "<script>alert(1)</script>" not in r.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in r.text
    assert "<b>bold</b>" not in r.text
    # The JSON in data-song cannot close its attribute.
    assert "it's" not in r.text.split("data-song=", 1)[1].split("</li>", 1)[0].split("'")[1]
    assert any(s["title"] == "it's <b>bold</b>" for s in songs_of(r.text))


@pytest.mark.parametrize(
    ("language", "expected"),
    [("es-ES,es;q=0.9", "Escuchar"), ("en-US", "Listen Now"), (None, "Listen Now")],
)
def test_languages(client: TestClient, ana: str, language: str | None, expected: str) -> None:
    headers = {"Accept-Language": language} if language else {}
    r = client.get("/web", headers=headers)
    assert f'<h1 class="large" tabindex="-1">{expected}</h1>' in r.text
    assert f'lang="{"es" if language and language.startswith("es") else "en"}"' in r.text


# ---------------------------------------------------------------------- the home page


def test_home_is_the_sign_in_form_without_a_session(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert 'action="/web/login"' in r.text
    assert "<audio" not in r.text
    assert r.headers["content-type"].startswith("text/html")
    assert r.headers["content-security-policy"].startswith("default-src 'none'")
    assert "media-src 'self'" in r.headers["content-security-policy"]
    hx = client.get("/", headers=HX)
    assert hx.status_code == 200
    assert hx.headers["hx-redirect"] == "/"


def test_home_is_listen_now_with_a_session(client: TestClient, ana: str) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "<audio" in r.text
    assert "Harbour Lights" in r.text
    assert 'href="/" data-nav' in r.text
    partial = client.get("/", headers=HX)
    assert "<audio" not in partial.text
    assert "Harbour Lights" in partial.text


def test_signing_in_lands_on_the_home_page(client: TestClient, people: object) -> None:
    from tests.web.conftest import People, csrf_of  # noqa: PLC0415

    assert isinstance(people, People)
    form = client.get("/")
    r = client.post(
        "/web/login",
        data={"csrf": csrf_of(form.text), "username": "ana", "password": people.ana.password},
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    assert "<audio" in client.get("/").text
