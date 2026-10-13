# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The web player's core: shared state, sessions and CSRF, error answers, rendering, static
files and sign-in/sign-out. The routes are in `pages.py`, `actions.py`, `api.py`,
`account.py` and `importing.py`.

- `/` (`pages.home`) is the player for browsers: Listen Now with a session, else the sign-in
  form. Everything else lives under `/web`.
- Pages are server-rendered Jinja. Navigation is HTMX (`hx-boost`): a request with `HX-Request`
  gets only the page's content, which replaces `#content`, so the player bar and its `<audio>`
  element outside it keep playing across pages; full loads get the whole shell.
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

from fastapi import APIRouter, Depends, Path, Request
from fastapi.routing import APIRoute
from starlette.datastructures import FormData
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from ultimatetunes import __version__
from ultimatetunes.admin.i18n import Lang, negotiate
from ultimatetunes.admin.repository import AdminRepository, audit
from ultimatetunes.admin.routes import form_data
from ultimatetunes.admin.security import (
    CSRF_FIELD,
    LOGIN_TTL_S,
    PENDING_2FA_TTL_S,
    SessionData,
    csrf_failure,
    csrf_ok,
    csrf_reason,
    session_rejected,
)
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
from ultimatetunes.web.backend import Backend
from ultimatetunes.web.i18n import translator
from ultimatetunes.web.security import (
    EPOCH_KEY,
    HOME,
    LANG_COOKIE,
    LOGIN_COOKIE,
    PENDING_2FA_COOKIE,
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
    "theme.js": ("web", "text/javascript"),
}
ItemId = Annotated[str, Path(alias="id", min_length=1, max_length=80)]
MAX_NAME = 200
LIBRARY_TABS = (
    ("/web/library", "Albums"),
    ("/web/library/artists", "Artists"),
    ("/web/library/playlists", "Playlists"),
    ("/web/library/favourites", "Favourites"),
)
# The sections of the navigation: (path, label, icon template).
SECTIONS = (
    ("/", "Listen Now", "_icon_listen.html"),
    ("/web/radio", "Radio", "_icon_radio.html"),
    ("/web/library", "Library", "_icon_library.html"),
    ("/web/search", "Search", "_icon_search.html"),
)
MESSAGES = {
    "signin": "Your session has ended. Sign in again.",
    "csrf": "The form expired or came from another site. Reload and retry.",
    "credentials": "Wrong username or password.",
    "attempts": "Too many attempts. Wait and try again.",
    "code": "That code is wrong.",
    "expired": "Your sign-in expired. Start again.",
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
    cookie = request.cookies.get(SESSION_COOKIE)
    session = st.codec.read_session(cookie)
    if session is None:
        if cookie:
            session_rejected("invalid_or_expired")
        raise SignInRequired
    try:
        user = st.auth.get_user(session.user_id)
    except NotFound as exc:
        session_rejected("unknown_user")
        raise SignInRequired from exc
    if user.is_disabled:
        session_rejected("account_disabled", user.username)
        raise SignInRequired
    with st.services.db.read() as conn:
        epoch = session_epoch(AdminRepository(conn), user.id)
    if st.codec.fingerprint(user.password_hash, epoch) != session.fingerprint:
        session_rejected("revoked", user.username)
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
        csrf_failure(request)
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
    """Pages and forms get the error page (HTMX swaps it into `#content`); the player's calls
    and the star buttons get JSON, which `player.js` shows in its status line."""
    if _is_page(request):
        try:
            listener = current_listener(request)
        except (SignInRequired, TunesError):
            listener = None
        return page(
            request,
            "error.html",
            {"message": None, "reason": MESSAGES["csrf"]},
            listener=listener,
            status=403,
        )
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


# ---------------------------------------------------------------------- rendering


def lang_of(request: Request) -> Lang:
    """The language chosen in Settings (a cookie), else the browser's (`Accept-Language`)."""
    chosen = request.cookies.get(LANG_COOKIE)
    if chosen == "es":
        return "es"
    if chosen == "en":
        return "en"
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
        "sections": SECTIONS,
    }
    values.update(context or {})
    html = state(request).templates.render(template, values)
    return HTMLResponse(html, status_code=status, headers={"Vary": "HX-Request"})


def go(request: Request, location: str) -> Response:
    """After a state change: HTMX swaps the target page in; plain forms follow a redirect."""
    if request.headers.get("hx-request"):
        return Response(status_code=200, headers={"HX-Location": json.dumps(_hx(location))})
    return RedirectResponse(location, status_code=303)


def _hx(location: str) -> dict[str, str]:
    return {"path": location, "target": "#content"}


async def data(
    request: Request, listener: Listener, endpoint: str, /, **params: Any
) -> dict[str, Any]:
    """The payload of an OpenSubsonic endpoint called as `listener` (`backend.Backend`)."""
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
    return login_page(request)


def login_page(request: Request, *, error: str | None = None, status: int = 200) -> Response:
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
        csrf_failure(request, csrf_reason(request, "login_token"))
        return login_page(request, error=MESSAGES["csrf"], status=403)
    username, password = form.get("username"), form.get("password")
    if not isinstance(username, str) or not isinstance(password, str) or not password:
        return login_page(request, error=MESSAGES["credentials"], status=400)
    ip = client_ip(request)
    try:
        user = st.auth.verify_password(username, password, ip, trusted=trusted_origin(request))
    except RateLimited:
        return login_page(request, error=MESSAGES["attempts"], status=429)
    except (AuthenticationFailed, AccountDisabled, Forbidden, InvalidParameter):
        return login_page(request, error=MESSAGES["credentials"], status=401)
    if st.auth.two_factor.is_enabled(user.id):
        # The password was right; hold the session until the second factor (`/web/login/2fa`).
        with st.services.db.read() as conn:
            epoch = session_epoch(AdminRepository(conn), user.id)
        cookie, pending = st.codec.new_pending_2fa(user.id, user.password_hash, epoch)
        response = _login_2fa_page(request, pending.csrf)
        set_cookie(response, PENDING_2FA_COOKIE, cookie, PENDING_2FA_TTL_S)
        clear_cookie(response, LOGIN_COOKIE)
        return response
    return _complete_login(request, user)


def _role_of(user: User) -> Role:
    return "admin" if user.role == "admin" else "user"


def _login_2fa_page(
    request: Request, csrf: str, *, error: str | None = None, status: int = 200
) -> Response:
    return page(
        request,
        "login_2fa.html",
        {"two_factor_csrf": csrf},
        listener=None,
        status=status,
        error=error,
    )


def _complete_login(request: Request, user: User) -> Response:
    """Issues the web session once every factor has passed, and audits the sign-in. A user the
    require-policy covers but who has not enrolled is sent to Settings to enroll."""
    st = state(request)
    ip = client_ip(request)
    with st.services.db.transaction() as conn:
        epoch = session_epoch(AdminRepository(conn), user.id)
        audit(conn, st.services.clock, actor_id=user.id, ip=ip, action="web.login")
    cookie, _session = st.codec.new_session(user.id, user.password_hash, epoch)
    target = (
        PREFIX + "/settings"
        if st.auth.two_factor.status(user.id, _role_of(user)).must_enroll
        else HOME
    )
    response = RedirectResponse(target, status_code=303)
    set_cookie(response, SESSION_COOKIE, cookie, st.codec.ttl_s)
    clear_cookie(response, LOGIN_COOKIE)
    clear_cookie(response, PENDING_2FA_COOKIE)
    return response


@router.post(PREFIX + "/login/2fa", include_in_schema=False)
def login_second_factor(
    request: Request, form: Annotated[FormData, Depends(form_data)]
) -> Response:
    """The second step after a correct password: a TOTP code or a recovery code. The pending
    cookie proves the password step passed (bound to the user's password fingerprint)."""
    st = state(request)
    pending = st.codec.read_pending_2fa(request.cookies.get(PENDING_2FA_COOKIE))
    token = form.get(CSRF_FIELD)
    submitted = token if isinstance(token, str) else None
    if pending is None or not csrf_ok(request, pending.csrf, submitted):
        csrf_failure(request, csrf_reason(request))
        return login_page(request, error=MESSAGES["expired"], status=403)
    try:
        user = st.auth.get_user(pending.user_id)
    except NotFound:
        return login_page(request, error=MESSAGES["expired"], status=403)
    with st.services.db.read() as conn:
        epoch = session_epoch(AdminRepository(conn), user.id)
    if user.is_disabled or st.codec.fingerprint(user.password_hash, epoch) != pending.fingerprint:
        return login_page(request, error=MESSAGES["expired"], status=403)
    code = form.get("code")
    code_value = code if isinstance(code, str) else ""
    if not st.auth.two_factor.verify_second_factor(user.id, code_value, client_ip(request)):
        return _login_2fa_page(request, pending.csrf, error=MESSAGES["code"], status=401)
    return _complete_login(request, user)


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


def new_session_cookie(response: Response, request: Request, user: User) -> None:
    """Signs `user` in on this browser (after the login form, or a new password)."""
    st = state(request)
    with st.services.db.read() as conn:
        epoch = session_epoch(AdminRepository(conn), user.id)
    cookie, _session = st.codec.new_session(user.id, user.password_hash, epoch)
    set_cookie(response, SESSION_COOKIE, cookie, st.codec.ttl_s)
