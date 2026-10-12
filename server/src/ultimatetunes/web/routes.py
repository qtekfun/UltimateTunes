# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The web player: the home page `/`, and under `/web` its pages, the player's JSON calls,
media and sign-in.

- `/` is the player for browsers: Listen Now with a session, else the sign-in form.

- Pages are server-rendered Jinja. Navigation is HTMX (`hx-boost`): a request with `HX-Request`
  gets only the page's content, which replaces `#content`, so the player bar and its `<audio>`
  element outside it keep playing across pages; full loads get the whole shell.
- `/web/api/*` (radio, lyrics, first-play status, scrobble) answer JSON to `player.js`.
- `/web/stream/{id}` and `/web/cover/{id}` are the OpenSubsonic `stream` and `getCoverArt`
  handlers (HTTP Range, streaming while downloading, the cover service) behind the session
  cookie: no API key in any URL.
- Every handler depends on `current_listener` (session, then the per-user request rate) and
  every state change on `posted` (session, then CSRF). Data goes through `backend.Backend`, the
  OpenSubsonic handlers called as the signed-in user.

Who may call what is decided in `security.py`. Errors: pages show an error page with the
status of the error; JSON and media calls answer `{"error", "message"}`.
"""

import json
import logging
from collections.abc import Callable, Coroutine, Mapping
from dataclasses import dataclass
from importlib import resources
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import FormData
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from ultimatetunes import __version__
from ultimatetunes.admin.i18n import Lang, negotiate
from ultimatetunes.admin.repository import AdminRepository, audit
from ultimatetunes.admin.routes import form_data
from ultimatetunes.admin.security import CSRF_FIELD, LOGIN_TTL_S, SessionData, csrf_ok
from ultimatetunes.auth.repository import User
from ultimatetunes.auth.service import AuthService
from ultimatetunes.auth.settings import AuthSettings
from ultimatetunes.core.authn import Principal, Role
from ultimatetunes.core.clock import format_ts
from ultimatetunes.core.forwarded import trusted_origin
from ultimatetunes.core.ratelimit import Limit
from ultimatetunes.core.services import Services
from ultimatetunes.errors import (
    AccountDisabled,
    AuthenticationFailed,
    Forbidden,
    InvalidParameter,
    NotFound,
    RateLimited,
    RetryLater,
    TunesError,
    spec_for,
)
from ultimatetunes.ids.virtual import parse_kind
from ultimatetunes.jobs import tracks
from ultimatetunes.web import backend
from ultimatetunes.web.backend import Backend
from ultimatetunes.web.i18n import translator
from ultimatetunes.web.security import (
    EPOCH_KEY,
    HOME,
    LOGIN_COOKIE,
    PREFIX,
    SESSION_COOKIE,
    WebSessionCodec,
    clear_cookie,
    set_cookie,
)
from ultimatetunes.web.settings import WebSettings

log = logging.getLogger(__name__)

STATIC_FILES = {
    "web.css": ("web", "text/css"),
    "player.js": ("web", "text/javascript"),
    "icon.svg": ("web", "image/svg+xml"),
    "blank.svg": ("web", "image/svg+xml"),
    # The panel's vendored copy (static/admin/htmx.min.js.license): one file, two users.
    "htmx.min.js": ("admin", "text/javascript"),
}
ItemId = Annotated[str, Path(alias="id", min_length=1, max_length=80)]
PAGE_SIZE = 60
MAX_OFFSET = 100_000
MAX_QUERY = 200
MAX_NAME = 200
RADIO_SIZE = 50
JSON_DATA = "application/json"
SEARCH_COUNTS = {"artistCount": "8", "albumCount": "12", "songCount": "30"}
LIBRARY_TABS = (
    ("/web/library", "Albums"),
    ("/web/library/artists", "Artists"),
    ("/web/library/playlists", "Playlists"),
    ("/web/library/favourites", "Favourites"),
)
MESSAGES = {
    "signin": "Your session has ended. Sign in again.",
    "csrf": "The form expired or came from another site. Reload and retry.",
    "credentials": "Wrong username or password.",
    "attempts": "Too many attempts. Wait and try again.",
}


# ---------------------------------------------------------------------- state and signals


@dataclass
class WebState:
    """What the web player shares across requests (in `app.state.web`). No request state."""

    services: Services
    auth: AuthService
    codec: WebSessionCodec
    settings: WebSettings
    auth_settings: AuthSettings
    templates: "Templates"
    backend: Backend


class Templates:
    def __init__(self) -> None:
        from jinja2 import Environment, PackageLoader, StrictUndefined  # noqa: PLC0415

        self.env = Environment(
            loader=PackageLoader("ultimatetunes", "templates/web"),
            autoescape=True,
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.env.filters["duration"] = duration
        self.env.filters["path_id"] = path_id
        self.env.globals["cover"] = cover_url

    def render(self, name: str, context: Mapping[str, object]) -> str:
        return self.env.get_template(name).render(context)


def duration(value: object) -> str:
    seconds = value if isinstance(value, int) and value > 0 else 0
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def path_id(value: object) -> str:
    return quote(str(value), safe="")


def cover_url(cover: object) -> str:
    return f"{PREFIX}/cover/{path_id(cover)}" if cover else f"{PREFIX}/static/blank.svg"


def state(request: Request) -> WebState:
    found: WebState = request.app.state.web
    return found


class SignInRequired(Exception):  # noqa: N818 - a control-flow signal, not an error
    """No valid session: pages go to the login form, everything else gets 401."""


class CsrfRejected(Exception):  # noqa: N818
    """A state change without the session's CSRF token, or a cross-site one."""


@dataclass(frozen=True)
class Listener:
    user: User
    session: SessionData
    ip: str | None

    @property
    def principal(self) -> Principal:
        role: Role = "admin" if self.user.role == "admin" else "user"
        return Principal(self.user.id, self.user.username, role)


@dataclass(frozen=True)
class Posted:
    listener: Listener
    form: FormData

    def get(self, name: str) -> str:
        value = self.form.get(name)
        return value if isinstance(value, str) else ""


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def session_epoch(repo: AdminRepository, user_id: str) -> int:
    """The user's web session epoch (0 until the first sign-out)."""
    raw = repo.setting(EPOCH_KEY + user_id)
    try:
        return int(raw) if raw is not None else 0
    except ValueError:
        return 0


def current_listener(request: Request) -> Listener:
    """The signed-in user, any role. Raises `SignInRequired`, or `RateLimited` when the user
    goes over the same request rate as one API key (`UT_AUTH_KEY_RATE_PER_S`/`_BURST`)."""
    st = state(request)
    session = st.codec.read_session(request.cookies.get(SESSION_COOKIE))
    if session is None:
        raise SignInRequired
    try:
        user = st.auth.get_user(session.user_id)
    except NotFound as exc:
        raise SignInRequired from exc
    if user.is_disabled:
        raise SignInRequired
    with st.services.db.read() as conn:
        epoch = session_epoch(AdminRepository(conn), user.id)
    if st.codec.fingerprint(user.password_hash, epoch) != session.fingerprint:
        raise SignInRequired
    limit = Limit(st.auth_settings.auth_key_rate_per_s, st.auth_settings.auth_key_burst)
    decision = st.services.rate_limiter.hit(f"web:user:{user.id}", limit)
    if not decision.allowed:
        raise RateLimited(decision.retry_after_s)
    return Listener(user, session, client_ip(request))


def posted(
    request: Request,
    listener: Annotated[Listener, Depends(current_listener)],
    form: Annotated[FormData, Depends(form_data)],
) -> Posted:
    """A state change: a session, then the CSRF token (checked in that order)."""
    token = form.get(CSRF_FIELD)
    if not csrf_ok(request, listener.session.csrf, token if isinstance(token, str) else None):
        raise CsrfRejected
    return Posted(listener, form)


ListenerDep = Annotated[Listener, Depends(current_listener)]
PostedDep = Annotated[Posted, Depends(posted)]


def _is_page(request: Request) -> bool:
    """Whether a failure answers an HTML page (pages and forms) rather than JSON (the player's
    calls, media and the star buttons, which HTMX swaps in place)."""
    path = request.url.path
    if path == f"{PREFIX}/star":
        return False
    return not any(path.startswith(f"{PREFIX}/{p}/") for p in ("api", "stream", "cover"))


def _status(error: TunesError) -> int:
    spec = spec_for(error)
    if spec.http_status is not None:
        return spec.http_status
    return spec.subsonic_http_status if spec.subsonic_http_status != 200 else 400  # noqa: PLR2004


def _error_response(request: Request, error: TunesError) -> Response:
    status = _status(error)
    headers = {"Retry-After": str(error.retry_after_s)} if isinstance(error, RetryLater) else {}
    if _is_page(request):
        try:
            listener = current_listener(request)
        except (SignInRequired, TunesError):
            listener = None
        response: Response = page(
            request, "error.html", {"message": error.message}, listener=listener, status=status
        )
        response.headers.update(headers)
        return response
    code = spec_for(error).problem_code or "error"
    return JSONResponse(
        {"error": code, "message": error.message}, status_code=status, headers=headers
    )


def _signed_out(request: Request) -> Response:
    if _is_page(request) and request.method == "GET":
        if request.headers.get("hx-request"):
            return Response(status_code=200, headers={"HX-Redirect": HOME})
        return RedirectResponse(HOME, status_code=303)
    headers = {"HX-Redirect": HOME} if request.headers.get("hx-request") else {}
    message = translator(lang_of(request))(MESSAGES["signin"])
    return JSONResponse(
        {"error": "authentication_required", "message": message}, status_code=401, headers=headers
    )


def _csrf_refused(request: Request) -> Response:
    message = translator(lang_of(request))(MESSAGES["csrf"])
    return JSONResponse({"error": "csrf", "message": message}, status_code=403)


class WebRoute(APIRoute):
    """Turns the web player's signals and `TunesError`s into its own answers (pages or JSON),
    instead of the problems of `/ut/v1`."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except SignInRequired:
                return _signed_out(request)
            except CsrfRejected:
                return _csrf_refused(request)
            except TunesError as error:
                return _error_response(request, error)

        return handler


router = APIRouter(route_class=WebRoute)
# `/` is always served (the sign-in form, Listen Now, or the plain page when turned off).
home_router = APIRouter(route_class=WebRoute)


# ---------------------------------------------------------------------- rendering


def lang_of(request: Request) -> Lang:
    return negotiate(request.headers.get("accept-language"))


def page(  # noqa: PLR0913 - the parts of one rendered page
    request: Request,
    template: str,
    context: Mapping[str, object] | None = None,
    *,
    listener: Listener | None,
    status: int = 200,
    error: str | None = None,
) -> HTMLResponse:
    lang = lang_of(request)
    _ = translator(lang)
    partial = bool(request.headers.get("hx-request")) and listener is not None
    values: dict[str, object] = {
        "_": _,
        "lang": lang,
        "version": __version__,
        "me": listener,
        "csrf": listener.session.csrf if listener else "",
        "path": request.url.path,
        "layout": "_partial.html" if partial else "base.html",
        "error": _(error) if error else None,
        "library_tabs": LIBRARY_TABS,
    }
    values.update(context or {})
    html = state(request).templates.render(template, values)
    return HTMLResponse(html, status_code=status, headers={"Vary": "HX-Request"})


def _go(request: Request, location: str) -> Response:
    """After a state change: HTMX swaps the target page in; plain forms follow a redirect."""
    if request.headers.get("hx-request"):
        return Response(status_code=200, headers={"HX-Location": json.dumps(_hx(location))})
    return RedirectResponse(location, status_code=303)


def _hx(location: str) -> dict[str, str]:
    return {"path": location, "target": "#content"}


async def _data(
    request: Request, listener: Listener, endpoint: str, /, **params: Any
) -> dict[str, Any]:
    return await state(request).backend.data(request, listener.principal, endpoint, params)


# ---------------------------------------------------------------------- static


@router.get(PREFIX + "/static/{name}", include_in_schema=False)
def static(name: str) -> Response:
    found = STATIC_FILES.get(name)
    if found is None:
        return Response("Not found", status_code=404, media_type="text/plain")
    folder, media_type = found
    body = (resources.files("ultimatetunes") / "static" / folder / name).read_bytes()
    return Response(body, media_type=media_type, headers={"Cache-Control": "max-age=3600"})


# ---------------------------------------------------------------------- sign in and out


@router.get(PREFIX + "/login", include_in_schema=False)
def login_form(request: Request) -> Response:
    return _login_page(request)


def _login_page(request: Request, *, error: str | None = None, status: int = 200) -> Response:
    cookie, token = state(request).codec.new_login_token()
    response = page(
        request, "login.html", {"login_token": token}, listener=None, status=status, error=error
    )
    set_cookie(response, LOGIN_COOKIE, cookie, LOGIN_TTL_S)
    return response


@router.post(PREFIX + "/login", include_in_schema=False)
def login(request: Request, form: Annotated[FormData, Depends(form_data)]) -> Response:
    """Username and password, checked by `AuthService.verify_password` with the lockout
    counter of the caller's origin (`trusted_origin`), exactly like `POST /ut/v1/keys`."""
    st = state(request)
    token = form.get(CSRF_FIELD)
    if request.headers.get("sec-fetch-site", "same-origin") not in (
        "same-origin",
        "none",
    ) or not st.codec.check_login_token(
        request.cookies.get(LOGIN_COOKIE), token if isinstance(token, str) else None
    ):
        return _login_page(request, error=MESSAGES["csrf"], status=403)
    username, password = form.get("username"), form.get("password")
    if not isinstance(username, str) or not isinstance(password, str) or not password:
        return _login_page(request, error=MESSAGES["credentials"], status=400)
    ip = client_ip(request)
    try:
        user = st.auth.verify_password(username, password, ip, trusted=trusted_origin(request))
    except RateLimited:
        return _login_page(request, error=MESSAGES["attempts"], status=429)
    except (AuthenticationFailed, AccountDisabled, Forbidden, InvalidParameter):
        return _login_page(request, error=MESSAGES["credentials"], status=401)
    with st.services.db.transaction() as conn:
        epoch = session_epoch(AdminRepository(conn), user.id)
        audit(conn, st.services.clock, actor_id=user.id, ip=ip, action="web.login")
    cookie, _session = st.codec.new_session(user.id, user.password_hash, epoch)
    response = RedirectResponse(HOME, status_code=303)
    set_cookie(response, SESSION_COOKIE, cookie, st.codec.ttl_s)
    clear_cookie(response, LOGIN_COOKIE)
    return response


@router.post(PREFIX + "/logout", include_in_schema=False)
def logout(request: Request, post: PostedDep) -> Response:
    st = state(request)
    user_id = post.listener.user.id
    with st.services.db.transaction() as conn:
        # Ends every web session of this user, copied cookies included.
        repo = AdminRepository(conn)
        epoch = session_epoch(repo, user_id) + 1
        repo.put_setting(EPOCH_KEY + user_id, str(epoch), format_ts(st.services.clock.now()))
        audit(conn, st.services.clock, actor_id=user_id, ip=post.listener.ip, action="web.logout")
    if request.headers.get("hx-request"):
        response: Response = Response(status_code=200, headers={"HX-Redirect": HOME})
    else:
        response = RedirectResponse(HOME, status_code=303)
    clear_cookie(response, SESSION_COOKIE)
    return response


# ---------------------------------------------------------------------- pages


@home_router.get(HOME, include_in_schema=False)
async def home(request: Request) -> Response:
    """The home page of the server: Listen Now with a session, else the sign-in form. With
    the web player turned off, a page that only says the server runs."""
    if not state(request).settings.web_enabled:
        return page(request, "landing.html", listener=None)
    try:
        me = await run_in_threadpool(current_listener, request)
    except SignInRequired:
        if request.headers.get("hx-request"):
            return Response(status_code=200, headers={"HX-Redirect": HOME})
        return _login_page(request)
    return await listen_now(request, me)


@router.get(PREFIX, include_in_schema=False)
async def listen_now(request: Request, me: ListenerDep) -> Response:
    recent = await _data(request, me, "getAlbumList2", type="recent", size="12")
    newest = await _data(request, me, "getAlbumList2", type="newest", size="18")
    context = {
        "recent": [backend.album(a) for a in backend.items(recent["albumList2"], "album")],
        "newest": [backend.album(a) for a in backend.items(newest["albumList2"], "album")],
    }
    return page(request, "listen.html", context, listener=me)


@router.get(PREFIX + "/", include_in_schema=False)
def slash() -> Response:
    return RedirectResponse(PREFIX, status_code=308)


@router.get(PREFIX + "/library", include_in_schema=False)
async def library_albums(
    request: Request,
    me: ListenerDep,
    offset: Annotated[int, Query(ge=0, le=MAX_OFFSET)] = 0,
) -> Response:
    found = await _data(
        request,
        me,
        "getAlbumList2",
        type="alphabeticalByName",
        size=str(PAGE_SIZE + 1),
        offset=str(offset),
    )
    albums = [backend.album(a) for a in backend.items(found["albumList2"], "album")]
    context = {
        "albums": albums[:PAGE_SIZE],
        "next_offset": offset + PAGE_SIZE if len(albums) > PAGE_SIZE else None,
        "prev_offset": max(offset - PAGE_SIZE, 0) if offset else None,
    }
    return page(request, "library_albums.html", context, listener=me)


@router.get(PREFIX + "/library/artists", include_in_schema=False)
async def library_artists(request: Request, me: ListenerDep) -> Response:
    found = await _data(request, me, "getArtists")
    groups = [
        {
            "name": str(group.get("name", "")),
            "artists": [backend.artist(a) for a in backend.items(group, "artist")],
        }
        for group in backend.items(found["artists"], "index")
    ]
    return page(request, "library_artists.html", {"groups": groups}, listener=me)


@router.get(PREFIX + "/library/playlists", include_in_schema=False)
async def library_playlists(request: Request, me: ListenerDep) -> Response:
    found = await _data(request, me, "getPlaylists")
    playlists = [backend.playlist(p) for p in backend.items(found["playlists"], "playlist")]
    return page(request, "library_playlists.html", {"playlists": playlists}, listener=me)


@router.get(PREFIX + "/library/favourites", include_in_schema=False)
async def library_favourites(request: Request, me: ListenerDep) -> Response:
    found = (await _data(request, me, "getStarred2"))["starred2"]
    context = {
        "artists": [backend.artist(a) for a in backend.items(found, "artist")],
        "albums": [backend.album(a) for a in backend.items(found, "album")],
        "songs": [backend.song(s) for s in backend.items(found, "song")],
    }
    return page(request, "library_favourites.html", context, listener=me)


@router.get(PREFIX + "/search", include_in_schema=False)
async def search(
    request: Request,
    me: ListenerDep,
    q: Annotated[str, Query(max_length=MAX_QUERY)] = "",
) -> Response:
    query = q.strip()
    context: dict[str, object] = {"q": query, "artists": [], "albums": [], "songs": []}
    if query:
        found = (await _data(request, me, "search3", query=query, **SEARCH_COUNTS))["searchResult3"]
        context["artists"] = [backend.artist(a) for a in backend.items(found, "artist")]
        context["albums"] = [backend.album(a) for a in backend.items(found, "album")]
        context["songs"] = [backend.song(s) for s in backend.items(found, "song")]
    return page(request, "search.html", context, listener=me)


@router.get(PREFIX + "/album/{id}", include_in_schema=False)
async def album_page(request: Request, me: ListenerDep, item_id: ItemId) -> Response:
    found = (await _data(request, me, "getAlbum", id=item_id))["album"]
    context = {
        "album": backend.album(found),
        "songs": [backend.song(s) for s in backend.items(found, "song")],
    }
    return page(request, "album.html", context, listener=me)


@router.get(PREFIX + "/artist/{id}", include_in_schema=False)
async def artist_page(request: Request, me: ListenerDep, item_id: ItemId) -> Response:
    found = (await _data(request, me, "getArtist", id=item_id))["artist"]
    context = {
        "artist": backend.artist(found),
        "albums": [backend.album(a) for a in backend.items(found, "album")],
    }
    return page(request, "artist.html", context, listener=me)


@router.get(PREFIX + "/playlist/{id}", include_in_schema=False)
async def playlist_page(request: Request, me: ListenerDep, item_id: ItemId) -> Response:
    found = (await _data(request, me, "getPlaylist", id=item_id))["playlist"]
    context = {
        "playlist": backend.playlist(found),
        "songs": [backend.song(s) for s in backend.items(found, "entry")],
    }
    return page(request, "playlist.html", context, listener=me)


@router.get(PREFIX + "/add/{id}", include_in_schema=False)
async def add_page(request: Request, me: ListenerDep, item_id: ItemId) -> Response:
    """Add a song to one of the caller's own playlists (or to a new one)."""
    parse_kind(item_id, "song")
    song = (await _data(request, me, "getSong", id=item_id))["song"]
    found = await _data(request, me, "getPlaylists")
    playlists = [backend.playlist(p) for p in backend.items(found["playlists"], "playlist")]
    context = {"song": backend.song(song), "playlists": [p for p in playlists if not p["readonly"]]}
    return page(request, "add.html", context, listener=me)


# ---------------------------------------------------------------------- changes


def _name(post: Posted) -> str:
    name = post.get("name").strip()
    if not name or len(name) > MAX_NAME:
        raise InvalidParameter(f"The name needs 1 to {MAX_NAME} characters")
    return name


@router.post(PREFIX + "/playlists", include_in_schema=False)
async def create_playlist(request: Request, post: PostedDep) -> Response:
    songs = [post.get("song")] if post.get("song") else []
    created = await _data(request, post.listener, "createPlaylist", name=_name(post), songId=songs)
    playlist_id = str(created["playlist"]["id"])
    return _go(request, f"{PREFIX}/playlist/{path_id(playlist_id)}")


@router.post(PREFIX + "/playlists/{id}/add", include_in_schema=False)
async def add_to_playlist(request: Request, post: PostedDep, item_id: ItemId) -> Response:
    song = post.get("song")
    if not song:
        raise InvalidParameter("Choose a song")
    await _data(request, post.listener, "updatePlaylist", playlistId=item_id, songIdToAdd=song)
    return _go(request, f"{PREFIX}/playlist/{path_id(item_id)}")


@router.post(PREFIX + "/playlists/{id}/remove", include_in_schema=False)
async def remove_from_playlist(request: Request, post: PostedDep, item_id: ItemId) -> Response:
    index = post.get("index")
    await _data(
        request, post.listener, "updatePlaylist", playlistId=item_id, songIndexToRemove=index
    )
    return _go(request, f"{PREFIX}/playlist/{path_id(item_id)}")


@router.post(PREFIX + "/playlists/{id}/delete", include_in_schema=False)
async def delete_playlist(request: Request, post: PostedDep, item_id: ItemId) -> Response:
    await _data(request, post.listener, "deletePlaylist", id=item_id)
    return _go(request, f"{PREFIX}/library/playlists")


_STAR_PARAM = {"song": "id", "album": "albumId", "artist": "artistId"}


@router.post(PREFIX + "/star", include_in_schema=False)
async def star(request: Request, post: PostedDep) -> Response:
    """Stars (`on=1`) or unstars (`on=0`) a song, album or artist; answers the new button."""
    kind, item_id, on = post.get("kind"), post.get("id"), post.get("on") == "1"
    param = _STAR_PARAM.get(kind)
    if param is None or not item_id or len(item_id) > 80:  # noqa: PLR2004
        raise InvalidParameter("Invalid star request")
    await _data(request, post.listener, "star" if on else "unstar", **{param: item_id})
    context = {"kind": kind, "item_id": item_id, "on": on}
    return page(request, "_star.html", context, listener=post.listener)


# ---------------------------------------------------------------------- player calls (JSON)


@router.get(PREFIX + "/api/radio/{id}", include_in_schema=False)
async def radio(request: Request, me: ListenerDep, item_id: ItemId) -> Response:
    found = await _data(request, me, "getSimilarSongs2", id=item_id, count=str(RADIO_SIZE))
    songs = [backend.song(s) for s in backend.items(found["similarSongs2"], "song")]
    return JSONResponse({"songs": songs})


@router.get(PREFIX + "/api/lyrics/{id}", include_in_schema=False)
async def lyrics(request: Request, me: ListenerDep, item_id: ItemId) -> Response:
    found = await _data(request, me, "getLyricsBySongId", id=item_id)
    structured = backend.items(found["lyricsList"], "structuredLyrics")
    return JSONResponse(backend.lyrics(structured))


@router.get(PREFIX + "/api/status/{id}", include_in_schema=False)
async def track_status(request: Request, me: ListenerDep, item_id: ItemId) -> Response:
    """The first-play state of a song, as `GET /ut/v1/tracks/{id}/status`."""
    parse_kind(item_id, "song")
    found = await run_in_threadpool(tracks.status, state(request).services, item_id)
    return JSONResponse(found.to_json())


@router.post(PREFIX + "/api/scrobble", include_in_schema=False)
async def scrobble(request: Request, post: PostedDep) -> Response:
    """`submission=false` when a song starts ("now playing"), `true` once it counts as played."""
    item_id = post.get("id")
    submission = "false" if post.get("submission") == "false" else "true"
    await _data(request, post.listener, "scrobble", id=item_id, submission=submission)
    return Response(status_code=204)


# ---------------------------------------------------------------------- media


async def _media(request: Request, me: Listener, name: str, item_id: str) -> Response:
    response = await state(request).backend.media(request, me.principal, name, {"id": item_id})
    if request.method != "HEAD":
        return response
    head = Response(status_code=response.status_code)
    head.raw_headers = list(response.raw_headers)
    return head


@router.api_route(PREFIX + "/stream/{id}", methods=["GET", "HEAD"], include_in_schema=False)
async def stream(request: Request, me: ListenerDep, item_id: ItemId) -> Response:
    return await _media(request, me, "stream", item_id)


@router.api_route(PREFIX + "/cover/{id}", methods=["GET", "HEAD"], include_in_schema=False)
async def cover(request: Request, me: ListenerDep, item_id: ItemId) -> Response:
    return await _media(request, me, "getCoverArt", item_id)
