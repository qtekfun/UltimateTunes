# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""System endpoints in JSON and XML, and `GET /ut/v1/server`."""

import pytest

from tests.library.harness import Harness, schema
from ultimatetunes import __version__
from ultimatetunes.radio.service import radio_settings
from ultimatetunes.search.service import search_settings

XML_HEAD = (
    '<?xml version="1.0" encoding="UTF-8"?>\n<subsonic-response xmlns="http://subsonic.org/restapi"'
)


@pytest.mark.parametrize(
    ("endpoint", "component", "payload"),
    [
        ("ping", "EmptyResponse", {}),
        ("getLicense", "GetLicenseResponse", {"license": {"valid": True}}),
        (
            "getOpenSubsonicExtensions",
            "GetOpenSubsonicExtensionsResponse",
            {
                "openSubsonicExtensions": [
                    {"name": "apiKeyAuthentication", "versions": [1]},
                    {"name": "formPost", "versions": [1]},
                    {"name": "songLyrics", "versions": [1]},
                ]
            },
        ),
        ("tokenInfo", "TokenInfoResponse", {"tokenInfo": {"username": "ana"}}),
        (
            "getMusicFolders",
            "GetMusicFoldersResponse",
            {"musicFolders": {"musicFolder": [{"id": 1, "name": "Music"}]}},
        ),
    ],
)
def test_system_json(
    lib: Harness, endpoint: str, component: str, payload: dict[str, object]
) -> None:
    body = lib.ok(endpoint, component)
    for key in ("status", "version", "type", "serverVersion", "openSubsonic"):
        body.pop(key)
    assert body == payload


def test_system_xml(lib: Harness) -> None:
    r = lib.rest("getMusicFolders", fmt="xml")
    assert r.headers["content-type"] == "application/xml; charset=utf-8"
    assert r.text.startswith(XML_HEAD)
    assert '<musicFolders>\n    <musicFolder id="1" name="Music"/>\n  </musicFolders>' in r.text
    assert '<license valid="true"/>' in lib.rest("getLicense", fmt="xml").text
    r = lib.client.post("/rest/ping.view", data={"apiKey": "utk_ana"})
    assert 'status="ok"' in r.text


def test_extensions_are_public_and_the_rest_needs_a_key(lib: Harness) -> None:
    r = lib.client.get("/rest/getOpenSubsonicExtensions", params={"f": "json"})
    assert r.json()["subsonic-response"]["status"] == "ok"
    assert lib.error("ping", key="utk_wrong") == 44


def test_token_info_needs_api_key_auth(lib: Harness) -> None:
    r = lib.client.get("/rest/tokenInfo", params={"f": "json", "u": "ana", "p": "utk_ana"})
    assert r.json()["subsonic-response"]["error"]["code"] == 44


def test_server_info(lib: Harness) -> None:
    r = lib.client.get("/ut/v1/server")
    assert r.status_code == 200
    body = r.json()
    schema("ut-v1.yaml", "ServerInfo").validate(body)
    assert body["name"] == "UltimateTunes"
    assert body["version"] == __version__
    assert body["openSubsonic"] == {
        "apiVersion": "1.16.1",
        "extensions": ["apiKeyAuthentication", "formPost", "songLyrics"],
    }
    assert body["capabilities"]["externalSearch"] is True
    assert body["capabilities"]["radio"] is True
    # PLAN T16 installs streaming while downloading.
    assert body["capabilities"]["streamingWhileDownloading"] is True


def test_server_info_announces_installed_streaming(lib: Harness) -> None:
    class Streams:
        async def serve(self, *args: object, **kwargs: object) -> None:
            raise AssertionError

    lib.client.app.state.pending_streams = Streams()  # type: ignore[attr-defined]
    caps = lib.client.get("/ut/v1/server").json()["capabilities"]
    assert caps["streamingWhileDownloading"] is True


def test_server_info_follows_the_switches(lib: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UT_EXTERNAL_SEARCH", "false")
    monkeypatch.setenv("UT_RADIO", "false")
    search_settings.cache_clear()
    radio_settings.cache_clear()
    try:
        caps = lib.client.get("/ut/v1/server").json()["capabilities"]
    finally:
        search_settings.cache_clear()
        radio_settings.cache_clear()
    assert caps["externalSearch"] is False
    assert caps["radio"] is False
