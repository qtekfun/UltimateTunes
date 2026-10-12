# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Covers (respx, no network): Cover Art Archive first with its redirect to archive.org, the
YouTube thumbnail as fallback, and every SSRF/size/type rule of contracts/ids.md."""

import httpx
import pytest
import respx

from ultimatetunes.tagging.covers import (
    MAX_COVER_BYTES,
    CoverFetcher,
    caa_host,
    youtube_host,
)

pytestmark = pytest.mark.anyio
RELEASE = "4d6f8a0c-3e5a-4b7c-8f9a-1b3d5f7a9c02"
GROUP = "7c8d9e0f-1a2b-4c3d-9e4f-5a6b7c8d9e04"
CAA_RELEASE = f"https://coverartarchive.org/release/{RELEASE}/front-500"
CAA_GROUP = f"https://coverartarchive.org/release-group/{GROUP}/front-500"
ARCHIVE = f"https://archive.org/download/mbid-{RELEASE}/mbid-{RELEASE}-1_thumb500.jpg"
STORAGE = "https://ia800.us.archive.org/1/items/cover.jpg"
THUMB = "https://i.ytimg.com/vi/Qx7Lm2pZ0aB/hqdefault.jpg"
JPEG = b"\xff\xd8\xff\xe0" + b"jpeg-bytes"
IMAGE = {"Content-Type": "image/jpeg"}


async def fetch(**kwargs: str | None) -> bytes | None:
    fields: dict[str, str | None] = {
        "release_id": RELEASE,
        "release_group_id": GROUP,
        "thumbnail_url": THUMB,
    }
    async with httpx.AsyncClient() as client:
        return await CoverFetcher(client).fetch(**(fields | kwargs))


def test_hosts() -> None:
    assert caa_host("coverartarchive.org")
    assert caa_host("ia800.us.archive.org")
    assert not caa_host("evilarchive.org")
    assert not caa_host("archive.org.evil.example")
    assert youtube_host("i.ytimg.com")
    assert not youtube_host("ytimg.com")


async def test_cover_art_archive_through_its_redirects(web: respx.MockRouter) -> None:
    web.get(CAA_RELEASE).respond(307, headers={"Location": ARCHIVE})
    web.get(ARCHIVE).respond(302, headers={"Location": "/1/items/cover.jpg"})
    web.get("https://archive.org/1/items/cover.jpg").respond(302, headers={"Location": STORAGE})
    web.get(STORAGE).respond(200, content=JPEG, headers=IMAGE)
    thumb = web.get(THUMB)
    assert await fetch() == JPEG
    assert not thumb.called


async def test_the_release_group_is_the_second_choice(web: respx.MockRouter) -> None:
    web.get(CAA_RELEASE).respond(404)
    web.get(CAA_GROUP).respond(200, content=JPEG, headers=IMAGE)
    assert await fetch() == JPEG


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(307, headers={"Location": "https://evil.example/x.jpg"}),
        httpx.Response(307, headers={"Location": "http://archive.org/x.jpg"}),
        httpx.Response(307, headers={"Location": "https://archive.org:8443/x.jpg"}),
        httpx.Response(307, headers={"Location": "https://user@archive.org/x.jpg"}),
        httpx.Response(307, headers={"Location": CAA_RELEASE}),  # a loop
        httpx.Response(200, content=JPEG, headers={"Content-Type": "text/html"}),
        httpx.Response(200, content=b"\x89PNG\r\n", headers={"Content-Type": "image/png"}),
        httpx.Response(200, content=b"\xff" * (MAX_COVER_BYTES + 1), headers=IMAGE),
        httpx.Response(500),
    ],
)
async def test_rejected_answers_fall_back_to_the_thumbnail(
    web: respx.MockRouter, answer: httpx.Response
) -> None:
    web.get(CAA_RELEASE).mock(return_value=answer)
    web.get(CAA_GROUP).respond(404)
    web.get(THUMB).respond(200, content=JPEG, headers=IMAGE)
    assert await fetch() == JPEG


async def test_the_thumbnail_follows_no_redirect(web: respx.MockRouter) -> None:
    web.get(THUMB).respond(302, headers={"Location": "https://i.ytimg.com/other.jpg"})
    other = web.get("https://i.ytimg.com/other.jpg")
    assert await fetch(release_id=None, release_group_id=None) is None
    assert not other.called


@pytest.mark.parametrize(
    "url",
    [
        "http://i.ytimg.com/vi/x/hq.jpg",
        "https://example.com/x.jpg",
        "https://169.254.169.254/latest",
        "file:///etc/passwd",
        "https://i.ytimg.com:444/x.jpg",
    ],
)
async def test_thumbnails_only_from_the_approved_hosts(web: respx.MockRouter, url: str) -> None:
    route = web.route()
    assert await fetch(release_id=None, release_group_id=None, thumbnail_url=url) is None
    assert not route.called


async def test_invalid_ids_and_errors_mean_no_cover(web: respx.MockRouter) -> None:
    caa = web.route(host="coverartarchive.org")
    web.get(THUMB).mock(side_effect=httpx.ConnectError("down"))
    assert await fetch(release_id="../../x", release_group_id="nope") is None
    assert not caa.called
    assert await fetch(release_id=None, release_group_id=None, thumbnail_url=None) is None
