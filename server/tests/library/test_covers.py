# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`getCoverArt`: library images, external thumbnails (host rules, size, cache), HEAD."""

import dataclasses
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from tests.library.harness import Harness
from tests.library.media import JPEG, PNG, mp3_tags, write_mp3, write_opus
from ultimatetunes.core.clock import FakeClock
from ultimatetunes.errors import NotFound
from ultimatetunes.library.covers import MAX_EXTERNAL_BYTES, CoverCache, check_url
from ultimatetunes.search.catalog import Thumbnail

THUMB = "https://i.ytimg.com/vi/Qx7Lm2pZ0aB/hqdefault.jpg"
ALBUM_THUMB = "https://i.ytimg.com/vi/Fk2Lp9QwXa1/hqdefault.jpg"
ARTIST_THUMB = "https://yt3.googleusercontent.com/fake-paper-lanterns=w544-h544"


def cover(lib: Harness, cover_id: str, **params: Any) -> httpx.Response:
    response: httpx.Response = lib.client.get(
        "/rest/getCoverArt", params={"apiKey": "utk_ana", "f": "json", "id": cover_id, **params}
    )
    return response


def code(response: httpx.Response) -> int:
    assert response.status_code == 200
    value: int = response.json()["subsonic-response"]["error"]["code"]
    return value


def test_album_cover_from_the_folder(lib: Harness) -> None:
    album = lib.ids()["Harbour Lights"]
    r = cover(lib, f"al-{album}", size="300")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.content == JPEG
    head = lib.client.head("/rest/getCoverArt", params={"apiKey": "utk_ana", "id": f"al-{album}"})
    assert head.status_code == 200
    assert head.content == b""
    assert head.headers["content-length"] == str(len(JPEG))
    assert r.headers["x-content-type-options"] == "nosniff"


def test_svg_files_are_never_served(lib: Harness) -> None:
    album = lib.ids()["Harbour Lights"]
    (lib.music / "evil.svg").write_text("<svg onload=alert(1)/>", encoding="utf-8")
    with lib.services.db.transaction() as conn:
        conn.execute("UPDATE albums SET cover_path = 'evil.svg' WHERE id = ?", (album,))
    # The stored SVG is ignored; the folder JPEG is served instead.
    assert cover(lib, f"al-{album}").content == JPEG


def test_album_cover_embedded_in_the_first_song(lib: Harness) -> None:
    r = cover(lib, f"al-{lib.ids()['Salt & Ember']}")
    assert r.headers["content-type"] == "image/png"
    assert r.content == PNG


@pytest.mark.parametrize("kind", ["opus", "mp3"])
def test_embedded_cover_of_other_formats(lib: Harness, kind: str) -> None:
    folder = lib.music / "Neon Harbor" / "Static Bloom"
    if kind == "opus":
        write_opus(
            folder / "a.opus",
            {"title": "A", "artist": "Neon Harbor", "album": "Static Bloom"},
            cover=JPEG,
        )
    else:
        write_mp3(folder / "a.mp3", mp3_tags("A", "Neon Harbor", "Static Bloom", cover=JPEG))
    from ultimatetunes.library.scan import LibraryScanner  # noqa: PLC0415

    LibraryScanner(lib.services.db, lib.services.library, lib.clock).scan()
    r = cover(lib, f"al-{lib.ids()['Static Bloom']}")
    assert r.content == JPEG
    assert r.headers["content-type"] == "image/jpeg"
    # The artist image falls back to their newest album's cover.
    assert cover(lib, f"ar-{lib.ids()['Neon Harbor']}").content == JPEG


def test_album_without_any_cover(lib: Harness) -> None:
    write_mp3(lib.music / "Plain" / "x.mp3", mp3_tags("X", "Plain", "Nothing"))
    from ultimatetunes.library.scan import LibraryScanner  # noqa: PLC0415

    LibraryScanner(lib.services.db, lib.services.library, lib.clock).scan()
    assert code(cover(lib, f"al-{lib.ids()['Nothing']}")) == 70
    assert code(cover(lib, f"ar-{lib.ids()['Plain']}")) == 70


def test_artist_cover(lib: Harness) -> None:
    artist = lib.ids()["The Paper Lanterns"]
    assert cover(lib, f"ar-{artist}").content == JPEG
    (lib.music / "lanterns.png").write_bytes(PNG)
    with lib.services.db.transaction() as conn:
        conn.execute("UPDATE artists SET image_path = 'lanterns.png' WHERE id = ?", (artist,))
    r = cover(lib, f"ar-{artist}")
    assert (r.headers["content-type"], r.content) == ("image/png", PNG)


def test_unknown_and_invalid_cover_ids(lib: Harness) -> None:
    assert code(cover(lib, "al-0199d6a2-4c1e-7b3a-9f10-2a6c8e01ffff")) == 70
    assert code(cover(lib, "ar-0199d6a2-4c1e-7b3a-9f10-2a6c8e01ffff")) == 70
    assert code(cover(lib, "pl-0199d6a2-4c1e-7b3a-9f10-2a6c8e01ffff")) == 70
    assert code(cover(lib, "../etc/passwd")) == 70
    assert code(cover(lib, lib.ids()["Brasas"])) == 70
    with lib.services.db.transaction() as conn:
        conn.execute("UPDATE albums SET cover_path = '../../x.jpg'")
        conn.execute("UPDATE albums SET cover_path = 'notes.txt' WHERE name = 'Salt & Ember'")
    # A bad stored path is ignored, the folder and embedded art still work.
    assert cover(lib, f"al-{lib.ids()['Harbour Lights']}").content == JPEG
    assert cover(lib, f"al-{lib.ids()['Salt & Ember']}").content == PNG


def test_playlist_cover_follows_visibility(lib: Harness) -> None:
    created = lib.ok("createPlaylist", name="Mix", songId=[lib.ids()["Brasas"]])
    playlist = created["playlist"]["id"]
    assert cover(lib, f"pl-{playlist}").content == PNG
    bob = lib.client.get(
        "/rest/getCoverArt", params={"apiKey": "utk_bob", "f": "json", "id": f"pl-{playlist}"}
    )
    assert code(bob) == 70
    empty = lib.ok("createPlaylist", name="Empty")["playlist"]["id"]
    assert code(cover(lib, f"pl-{empty}")) == 70


@respx.mock
def test_external_song_thumbnail_is_fetched_once(lib: Harness) -> None:
    route = respx.get(THUMB).mock(
        return_value=httpx.Response(200, content=JPEG, headers={"Content-Type": "image/jpeg"})
    )
    r = cover(lib, "yt:Qx7Lm2pZ0aB")
    assert (r.status_code, r.headers["content-type"], r.content) == (200, "image/jpeg", JPEG)
    again = cover(lib, "yt:Qx7Lm2pZ0aB")
    assert again.content == JPEG
    assert route.call_count == 1
    files = list((lib.services.settings.data_dir / "covers").iterdir())
    assert len(files) == 1
    assert files[0].name.endswith(".jpeg")


@respx.mock
def test_external_album_and_artist_thumbnails(lib: Harness) -> None:
    respx.get(ALBUM_THUMB).mock(
        return_value=httpx.Response(200, content=PNG, headers={"Content-Type": "image/png"})
    )
    respx.get(ARTIST_THUMB).mock(
        return_value=httpx.Response(
            200, content=JPEG, headers={"Content-Type": "image/jpeg; charset=binary"}
        )
    )
    assert cover(lib, "ytalbum:MPREb_k3Vd9QmT2xL").content == PNG
    assert cover(lib, "ytartist:UCq8XbV1r0LwZ5mN3tYp7kQe").content == JPEG
    assert code(cover(lib, "ytalbum:MPREb_unknown")) == 70


@respx.mock
def test_pending_song_uses_its_stored_thumbnail(lib: Harness) -> None:
    stored = "https://lh3.googleusercontent.com/stored-thumb"
    respx.get(stored).mock(
        return_value=httpx.Response(200, content=PNG, headers={"Content-Type": "image/png"})
    )
    with lib.services.db.transaction() as conn:
        conn.execute(
            "INSERT INTO tracks (id, status, title, title_norm, artist_name, yt_video_id,"
            " yt_thumbnail_url, created_at, updated_at)"
            " VALUES (?, 'pending', 'P', 'p', 'A', 'Hm3Vx8Nq2Lp', ?, ?, ?)",
            (
                "0199d6a2-4c1e-7b3a-9f10-2a6c8e01c0bb",
                stored,
                "2026-10-12T08:00:00.000Z",
                "2026-10-12T08:00:00.000Z",
            ),
        )
    assert cover(lib, "yt:Hm3Vx8Nq2Lp").content == PNG
    assert lib.catalog.calls == []


def test_archived_song_shows_its_album_cover(lib: Harness) -> None:
    with lib.services.db.transaction() as conn:
        conn.execute(
            "INSERT INTO track_aliases (alias, track_id, created_at) VALUES (?, ?, ?)",
            ("yt:Wq5Jd7HsKe2", lib.ids()["Tidewater"], "2026-10-12T08:00:00.000Z"),
        )
    assert cover(lib, "yt:Wq5Jd7HsKe2").content == JPEG


@pytest.mark.parametrize(
    ("status", "headers", "body"),
    [
        (302, {"Location": "https://i.ytimg.com/other.jpg"}, b""),
        (404, {"Content-Type": "image/jpeg"}, b""),
        (200, {"Content-Type": "text/html"}, b"<html>"),
        (200, {"Content-Type": "image/jpeg", "Content-Length": str(MAX_EXTERNAL_BYTES + 1)}, b"x"),
        (200, {"Content-Type": "image/svg+xml"}, b"<svg/>"),
        (200, {"Content-Type": "image/x-icon"}, b"ico"),
    ],
)
@respx.mock
def test_external_thumbnail_rules(
    lib: Harness, status: int, headers: dict[str, str], body: bytes
) -> None:
    respx.get(THUMB).mock(return_value=httpx.Response(status, headers=headers, content=body))
    assert code(cover(lib, "yt:Qx7Lm2pZ0aB")) == 70
    assert not (lib.services.settings.data_dir / "covers").exists()


def _chunks(total: int, size: int = 64 * 1024) -> Any:
    async def body() -> Any:
        sent = 0
        while sent < total:
            chunk = min(size, total - sent)
            sent += chunk
            yield b"x" * chunk

    return body()


@respx.mock
def test_streamed_body_over_the_cap_without_content_length(lib: Harness) -> None:
    # A chunked answer (no Content-Length): only the count while streaming can stop it.
    route = respx.get(THUMB).mock(
        return_value=httpx.Response(
            200, headers={"Content-Type": "image/jpeg"}, stream=_chunks(MAX_EXTERNAL_BYTES + 1)
        )
    )
    assert code(cover(lib, "yt:Qx7Lm2pZ0aB")) == 70
    answer = route.calls.last.response
    assert "content-length" not in answer.headers
    assert not (lib.services.settings.data_dir / "covers").exists()


@respx.mock
def test_streamed_body_at_the_cap_is_served(lib: Harness) -> None:
    respx.get(THUMB).mock(
        return_value=httpx.Response(
            200, headers={"Content-Type": "image/png"}, stream=_chunks(MAX_EXTERNAL_BYTES)
        )
    )
    r = cover(lib, "yt:Qx7Lm2pZ0aB")
    assert r.status_code == 200
    assert len(r.content) == MAX_EXTERNAL_BYTES
    assert r.headers["x-content-type-options"] == "nosniff"


@respx.mock
def test_external_thumbnail_network_error(lib: Harness) -> None:
    respx.get(THUMB).mock(side_effect=httpx.ConnectError("down"))
    assert code(cover(lib, "yt:Qx7Lm2pZ0aB")) == 0


def test_catalog_thumbnail_on_another_host_is_refused(lib: Harness) -> None:
    track = lib.catalog.tracks["Qx7Lm2pZ0aB"]
    lib.catalog.tracks["Qx7Lm2pZ0aB"] = dataclasses.replace(
        track, thumbnail=Thumbnail("https://images.example.net/x.jpg")
    )
    assert code(cover(lib, "yt:Qx7Lm2pZ0aB")) == 70
    lib.catalog.tracks["Qx7Lm2pZ0aB"] = dataclasses.replace(track, thumbnail=None)
    assert code(cover(lib, "yt:Qx7Lm2pZ0aB")) == 70


@pytest.mark.parametrize(
    "url",
    [
        "http://i.ytimg.com/vi/x.jpg",
        "https://i.ytimg.com.evil.example/x.jpg",
        "https://user@i.ytimg.com/x.jpg",
        "https://i.ytimg.com:8443/x.jpg",
        "https://i.ytimg.com:bad/x.jpg",
        "https://127.0.0.1/x.jpg",
        "file:///etc/passwd",
    ],
)
def test_check_url_refuses(url: str) -> None:
    with pytest.raises(NotFound):
        check_url(url)


def test_check_url_accepts_the_approved_hosts() -> None:
    for host in (
        "i.ytimg.com",
        "lh3.googleusercontent.com",
        "yt3.ggpht.com",
        "YT3.googleusercontent.com",
    ):
        assert check_url(f"https://{host}:443/a") == f"https://{host}:443/a"


def test_cover_cache_ttl_and_size_cap(tmp_path: Path) -> None:
    clock = FakeClock()
    cache = CoverCache(tmp_path / "covers", clock, ttl_s=100, max_bytes=25)
    assert cache.get("yt:a") is None
    cache.put("yt:a", b"x" * 10, "image/png")
    assert cache.get("yt:a") == (b"x" * 10, "image/png")
    clock.advance(10)
    cache.put("yt:svg", b"<svg/>", "image/svg+xml")
    assert cache.get("yt:svg") is None
    cache.put("yt:b", b"y" * 10, "image/jpg; q=1")
    assert cache.get("yt:b") == (b"y" * 10, "image/jpeg")
    clock.advance(10)
    cache.put("yt:c", b"z" * 10, "image/webp")
    # Over 25 bytes: the oldest entry is evicted.
    assert cache.get("yt:a") is None
    assert cache.get("yt:b") is not None
    clock.advance(101)
    assert cache.get("yt:c") is None
    cache.put("yt:c", b"new", "image/gif")
    assert cache.get("yt:c") == (b"new", "image/gif")
    assert len([p for p in (tmp_path / "covers").iterdir() if p.name.startswith(".")]) == 0
