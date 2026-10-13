# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`YTMusicCatalog` on a scripted `YTMusic` and `YouTubeSession` on a canned transport.

No test reaches the network: respx cannot intercept `requests`, so HTTP is a mounted
`requests` adapter and ytmusicapi calls are a `YTMusic` subclass that answers fixtures.
"""

import json
import threading
from collections.abc import Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, override

import pytest
import requests
from requests.adapters import BaseAdapter
from ytmusicapi import YTMusic
from ytmusicapi.exceptions import YTMusicGatedError, YTMusicServerError, YTMusicUserError

from ultimatetunes.errors import InvalidId
from ultimatetunes.search.catalog import (
    CatalogClientError,
    CatalogNotFound,
    CatalogParseError,
    CatalogThrottled,
    CatalogUnavailable,
)
from ultimatetunes.search.settings import SearchSettings
from ultimatetunes.search.ytmusic import (
    HostRefused,
    HttpStatusError,
    YouTubeSession,
    YTMusicBackend,
    YTMusicCatalog,
    map_error,
    ytmusic_factory,
)

pytestmark = pytest.mark.anyio
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class Canned(BaseAdapter):
    """Answers every request with `status` and records the timeout it was sent with."""

    def __init__(self, status: int = 200, body: bytes = b"{}") -> None:
        super().__init__()
        self.status = status
        self.body = body
        self.timeouts: list[object] = []

    @override
    def send(
        self,
        request: requests.PreparedRequest,
        stream: bool = False,
        timeout: Any = None,
        verify: Any = True,
        cert: Any = None,
        proxies: Mapping[str, str] | None = None,
    ) -> requests.Response:
        self.timeouts.append(timeout)
        response = requests.Response()
        response.status_code = self.status
        response._content = self.body
        response.request = request
        response.url = request.url or ""
        return response

    @override
    def close(self) -> None:
        pass


def session_with(adapter: Canned, timeout_s: float = 5.0) -> YouTubeSession:
    session = YouTubeSession(timeout_s)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def test_session_sets_the_timeout_and_allows_only_youtube_music() -> None:
    adapter = Canned()
    session = session_with(adapter, 5.0)
    assert session.get("https://music.youtube.com/").status_code == 200
    assert session.post("https://music.youtube.com/youtubei/v1/search", timeout=99).ok
    assert adapter.timeouts == [5.0, 5.0]
    for url in ("http://music.youtube.com/", "https://www.youtube.com/", "https://evil.example/"):
        with pytest.raises(HostRefused):
            session.get(url)
    assert len(adapter.timeouts) == 2


@pytest.mark.parametrize("status", [400, 403, 404, 429, 500, 503])
def test_session_raises_http_errors_with_their_status(status: int) -> None:
    with pytest.raises(HttpStatusError) as raised:
        session_with(Canned(status)).get("https://music.youtube.com/")
    assert raised.value.status == status


def test_a_429_page_never_reaches_the_ytmusicapi_parser() -> None:
    yt = YTMusic(requests_session=session_with(Canned(429, b"<html>sorry</html>")))
    with pytest.raises(HttpStatusError) as raised:
        yt.search("x", filter="songs")
    assert isinstance(map_error(raised.value, lookup=False), CatalogThrottled)


@pytest.mark.parametrize(
    ("error", "lookup", "expected"),
    [
        (HttpStatusError(429), False, CatalogThrottled),
        (HttpStatusError(403), True, CatalogThrottled),
        (HttpStatusError(502), True, CatalogUnavailable),
        (HttpStatusError(404), True, CatalogNotFound),
        (HttpStatusError(400), False, CatalogClientError),
        (HttpStatusError(410), True, CatalogNotFound),
        (HttpStatusError(404), False, CatalogUnavailable),
        (requests.ConnectTimeout(), False, CatalogUnavailable),
        (requests.ConnectionError(), True, CatalogUnavailable),
        (HostRefused(), True, CatalogUnavailable),
        (YTMusicGatedError("gated"), False, CatalogThrottled),
        (YTMusicServerError("No content returned by the server."), True, CatalogNotFound),
        (YTMusicServerError("odd"), False, CatalogParseError),
        (YTMusicUserError("bad argument"), False, YTMusicUserError),
        (KeyError("contents"), True, CatalogNotFound),
        (KeyError("contents"), False, CatalogParseError),
        (IndexError(), False, CatalogParseError),
        (TypeError(), True, CatalogNotFound),
        (ValueError(), False, CatalogParseError),
        (InvalidId(), True, InvalidId),
        (RuntimeError("bug"), True, RuntimeError),
    ],
)
def test_error_mapping(error: Exception, lookup: bool, expected: type[Exception]) -> None:
    mapped = map_error(error, lookup=lookup)
    assert type(mapped) is expected
    if expected in (YTMusicUserError, RuntimeError, InvalidId):
        assert mapped is error


def test_factory_builds_an_english_client_on_our_session() -> None:
    settings = SearchSettings(ytm_location="ES", ytm_timeout_s=2.5)
    yt = ytmusic_factory(settings)()
    assert yt.language == "en"
    assert yt.context["context"]["client"]["gl"] == "ES"
    session = yt._session
    assert isinstance(session, YouTubeSession)
    assert session.timeout_s == 2.5


class ScriptedYTMusic(YTMusic):
    """Answers each method from `answers` (a value, or an exception to raise)."""

    def __init__(self, answers: dict[str, object]) -> None:
        super().__init__()
        self.answers = answers
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def _answer(self, name: str, *args: object, **kwargs: object) -> Any:
        self.calls.append((name, args, kwargs))
        answer = self.answers[name]
        if isinstance(answer, Exception):
            raise answer
        return answer

    @override
    def search(self, query: str, *args: Any, **kwargs: Any) -> Any:
        filter_ = kwargs.get("filter")
        return self._answer(f"search:{filter_}", query, **kwargs)

    @override
    def get_album(self, browseId: str) -> Any:
        return self._answer("get_album", browseId)

    @override
    def get_artist(self, channelId: str) -> Any:
        return self._answer("get_artist", channelId)

    @override
    def get_watch_playlist(self, *args: Any, **kwargs: Any) -> Any:
        return self._answer("get_watch_playlist", *args, **kwargs)

    @override
    def get_playlist(self, playlistId: str, *args: Any, **kwargs: Any) -> Any:
        return self._answer("get_playlist", playlistId, *args, **kwargs)

    @override
    def get_charts(self, country: str = "ZZ") -> Any:
        return self._answer("get_charts", country)

    @override
    def get_mood_categories(self) -> Any:
        return self._answer("get_mood_categories")

    @override
    def get_mood_playlists(self, params: str) -> Any:
        return self._answer("get_mood_playlists", params)


ANSWERS: dict[str, object] = {
    "search:songs": load("search_songs.json"),
    "search:albums": load("search_albums.json"),
    "search:artists": load("search_artists.json"),
    "get_album": load("album.json"),
    "get_artist": load("artist.json"),
    "get_watch_playlist": load("watch_playlist.json"),
    "get_playlist": load("playlist.json"),
}


@pytest.fixture
def executor() -> Iterator[ThreadPoolExecutor]:
    pool = ThreadPoolExecutor(2)
    yield pool
    pool.shutdown()


def catalog_for(yt: ScriptedYTMusic, executor: ThreadPoolExecutor) -> YTMusicCatalog:
    return YTMusicCatalog(YTMusicBackend(lambda: yt), executor)


async def test_catalog_calls_and_parses(executor: ThreadPoolExecutor) -> None:
    yt = ScriptedYTMusic(dict(ANSWERS))
    catalog = catalog_for(yt, executor)
    songs = await catalog.search_songs("lanterns", 20)
    assert [s.video_id for s in songs] == ["Fk2Lp9QwXa1", "Qx7Lm2pZ0aB", "Mx1Vb2Nc3Za"]
    assert [a.browse_id for a in await catalog.search_albums("lanterns", 20)] == [
        "MPREb_k3Vd9QmT2xL",
        "MPREb_Hn2Vq8Lr5Tz",
    ]
    assert len(await catalog.search_artists("lanterns", 20)) == 2
    assert len((await catalog.album("MPREb_k3Vd9QmT2xL")).tracks) == 2
    assert (await catalog.artist("UCq8XbV1r0LwZ5mN3tYp7kQe")).ref.name == "The Paper Lanterns"
    assert (await catalog.track("Fk2Lp9QwXa1")).title == "Low Tide Letters"
    radio = await catalog.radio("Fk2Lp9QwXa1", 2)
    assert [t.video_id for t in radio] == ["Fk2Lp9QwXa1", "Tz9Kd4Wb7Rc"]
    playlist = await catalog.playlist("VLPLfakeRoadTrip0123456789abcdefGH")
    assert playlist.playlist_id == "PLfakeRoadTrip0123456789abcdefGH"
    assert yt.calls == [
        ("search:songs", ("lanterns",), {"filter": "songs", "limit": 20}),
        ("search:albums", ("lanterns",), {"filter": "albums", "limit": 20}),
        ("search:artists", ("lanterns",), {"filter": "artists", "limit": 20}),
        ("get_album", ("MPREb_k3Vd9QmT2xL",), {}),
        ("get_artist", ("UCq8XbV1r0LwZ5mN3tYp7kQe",), {}),
        ("get_watch_playlist", (), {"videoId": "Fk2Lp9QwXa1", "limit": 1, "radio": False}),
        ("get_watch_playlist", (), {"videoId": "Fk2Lp9QwXa1", "limit": 2, "radio": True}),
        ("get_playlist", ("PLfakeRoadTrip0123456789abcdefGH",), {"limit": None}),
    ]


async def test_malformed_ids_never_reach_youtube(executor: ThreadPoolExecutor) -> None:
    yt = ScriptedYTMusic(dict(ANSWERS))
    catalog = catalog_for(yt, executor)
    for call in (
        catalog.album("MPREb/../x"),
        catalog.artist(""),
        catalog.track("short"),
        catalog.radio("Fk2Lp9QwXa1\n", 5),
        catalog.playlist("PL x"),
        catalog.playlist("VL"),
    ):
        with pytest.raises(CatalogNotFound):
            await call
    assert yt.calls == []


async def test_unknown_ids_are_not_found(executor: ThreadPoolExecutor) -> None:
    yt = ScriptedYTMusic(
        {
            "get_album": KeyError("contents"),
            "get_artist": KeyError("header"),
            "get_playlist": KeyError("contents"),
            "get_watch_playlist": YTMusicServerError("No content returned by the server."),
        }
    )
    catalog = catalog_for(yt, executor)
    for call in (
        catalog.album("MPREb_unknown"),
        catalog.artist("UCunknown"),
        catalog.playlist("PLunknown0"),
        catalog.radio("Unknown0001", 5),
        catalog.track("Unknown0001"),
    ):
        with pytest.raises(CatalogNotFound):
            await call


async def test_empty_or_mismatched_watch_playlists(executor: ThreadPoolExecutor) -> None:
    yt = ScriptedYTMusic({"get_watch_playlist": {"tracks": []}})
    catalog = catalog_for(yt, executor)
    with pytest.raises(CatalogNotFound):
        await catalog.radio("Fk2Lp9QwXa1", 5)


# ---------------------------------------------------------------------- charts & moods

_CHART_PLAYLIST = {
    "title": "Chart songs (fake)",
    "tracks": [
        {"videoId": "Fk2Lp9QwXa1", "title": "Low Tide Letters", "artists": []},
        {"videoId": "Tz9Kd4Wb7Rc", "title": "Signal Fires", "artists": []},
    ],
    "trackCount": 2,
}


async def test_charts_fetches_the_top_playlist_songs(executor: ThreadPoolExecutor) -> None:
    yt = ScriptedYTMusic(
        {
            "get_charts": {"videos": [{"playlistId": "VLPLchart0000"}], "artists": []},
            "get_playlist": _CHART_PLAYLIST,
        }
    )
    catalog = catalog_for(yt, executor)
    songs = await catalog.charts("ES")
    assert [s.video_id for s in songs] == ["Fk2Lp9QwXa1", "Tz9Kd4Wb7Rc"]
    assert yt.calls[0] == ("get_charts", ("ES",), {})
    assert yt.calls[1] == ("get_playlist", ("PLchart0000",), {"limit": None})


async def test_charts_without_a_usable_playlist_is_empty(executor: ThreadPoolExecutor) -> None:
    yt = ScriptedYTMusic({"get_charts": {"artists": []}})
    catalog = catalog_for(yt, executor)
    assert await catalog.charts("ZZ") == []


async def test_charts_rejects_a_bad_country(executor: ThreadPoolExecutor) -> None:
    yt = ScriptedYTMusic({})
    catalog = catalog_for(yt, executor)
    for country in ("spain", "es", "E1", ""):
        with pytest.raises(CatalogNotFound):
            await catalog.charts(country)
    assert yt.calls == []


async def test_moods_and_mood_tracks(executor: ThreadPoolExecutor) -> None:
    yt = ScriptedYTMusic(
        {
            "get_mood_categories": {
                "Moods & moments": [{"title": "Chill", "params": "ggChill000"}],
                "Genres": [{"title": "Pop", "params": "ggPop00000"}],
            },
            "get_mood_playlists": [{"playlistId": "VLPLmood0000"}],
            "get_playlist": _CHART_PLAYLIST,
        }
    )
    catalog = catalog_for(yt, executor)
    moods = await catalog.moods()
    assert [(m.params, m.title) for m in moods] == [
        ("ggChill000", "Chill"),
        ("ggPop00000", "Pop"),
    ]
    songs = await catalog.mood_tracks("ggChill000")
    assert [s.video_id for s in songs] == ["Fk2Lp9QwXa1", "Tz9Kd4Wb7Rc"]
    assert ("get_mood_playlists", ("ggChill000",), {}) in yt.calls


async def test_mood_tracks_rejects_a_bad_params(executor: ThreadPoolExecutor) -> None:
    yt = ScriptedYTMusic({})
    catalog = catalog_for(yt, executor)
    with pytest.raises(CatalogNotFound):
        await catalog.mood_tracks("bad params!")
    assert yt.calls == []


async def test_mood_tracks_without_a_playlist_is_empty(executor: ThreadPoolExecutor) -> None:
    yt = ScriptedYTMusic({"get_mood_playlists": []})
    catalog = catalog_for(yt, executor)
    assert await catalog.mood_tracks("ggChill000") == []
    yt.answers["get_watch_playlist"] = load("watch_playlist.json")
    with pytest.raises(CatalogNotFound):
        await catalog.track("Other000001")


async def test_search_failures(executor: ThreadPoolExecutor) -> None:
    yt = ScriptedYTMusic(
        {
            "search:songs": KeyError("tabs"),
            "search:albums": requests.ReadTimeout(),
            "search:artists": RuntimeError("bug"),
        }
    )
    catalog = catalog_for(yt, executor)
    with pytest.raises(CatalogParseError):
        await catalog.search_songs("x", 5)
    with pytest.raises(CatalogUnavailable):
        await catalog.search_albums("x", 5)
    with pytest.raises(RuntimeError):
        await catalog.search_artists("x", 5)


def test_one_client_per_thread() -> None:
    built: list[YTMusic] = []

    def factory() -> YTMusic:
        built.append(ScriptedYTMusic({}))
        return built[-1]

    backend = YTMusicBackend(factory)
    first = backend.client()
    assert backend.client() is first
    other: list[YTMusic] = []
    thread = threading.Thread(target=lambda: other.append(backend.client()))
    thread.start()
    thread.join()
    assert other[0] is not first
    assert len(built) == 2


async def test_production_build_contacts_nothing() -> None:
    catalog = YTMusicCatalog.build(SearchSettings(ytm_threads=1))
    assert isinstance(catalog, YTMusicCatalog)
