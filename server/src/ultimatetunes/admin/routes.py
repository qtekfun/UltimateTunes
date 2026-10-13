# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The admin panel at `/admin` (SPEC RF-10). (`/` is the web player's, `web/routes.py`.)

Server-rendered Jinja pages; HTMX (vendored, `static/admin/`) only refreshes the download queue.
Every page works without JavaScript. Who may call what is decided in `security.py`; every
handler here depends on `current_admin` (pages) or `posted` (state changes: admin + CSRF),
except the login form and the two static files.

State changes answer with a redirect back to their page (`?done=<code>`, a fixed message) or
with the page and an error message. Users, keys and the audit log go through T04's
`AuthService`; jobs through `JobQueue`; library files through `LibraryStore`.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib import resources
from typing import Annotated
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Depends, Request
from markupsafe import Markup
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import FormData
from starlette.responses import HTMLResponse, RedirectResponse, Response

from ultimatetunes import __version__
from ultimatetunes.admin import notify, qr
from ultimatetunes.admin.i18n import Lang, negotiate, translator
from ultimatetunes.admin.repository import (
    JOB_STATES,
    PAGE_SIZE,
    WORKER_COMMANDS,
    AdminRepository,
    audit,
    detail_text,
)
from ultimatetunes.admin.security import (
    CSRF_FIELD,
    LOGIN_COOKIE,
    LOGIN_TTL_S,
    PENDING_2FA_COOKIE,
    PENDING_2FA_TTL_S,
    SESSION_COOKIE,
    SessionCodec,
    SessionData,
    clear_cookie,
    csrf_failure,
    csrf_ok,
    csrf_reason,
    not_admin,
    session_rejected,
    set_cookie,
)
from ultimatetunes.admin.settings import AdminSettings
from ultimatetunes.auth.repository import User
from ultimatetunes.auth.service import ADMIN_EPOCH_PREFIX, AuthService
from ultimatetunes.core.authn import Principal
from ultimatetunes.core.clock import format_ts
from ultimatetunes.core.forwarded import trusted_origin
from ultimatetunes.core.limits import DownloadLimits
from ultimatetunes.core.ratelimit import Limit
from ultimatetunes.core.services import Services
from ultimatetunes.errors import (
    AccountDisabled,
    AuthenticationFailed,
    Conflict,
    Forbidden,
    InvalidParameter,
    NotFound,
    RateLimited,
    TunesError,
)
from ultimatetunes.jobs.gate import LOW_DISK_KEY, window_start
from ultimatetunes.jobs.queue import PRIORITY_KEEP
from ultimatetunes.search import guard
from ultimatetunes.search import service as search_service
from ultimatetunes.search.guard import GuardedCatalog
from ultimatetunes.search.settings import SearchSettings

log = logging.getLogger(__name__)
router = APIRouter()

STATIC_FILES = {
    "htmx.min.js": ("admin", "text/javascript"),
    "admin.js": ("admin", "text/javascript"),
    "admin.css": ("admin", "text/css"),
    # The web player's logo (static/web/icon.svg): one file, two users.
    "icon.svg": ("web", "image/svg+xml"),
}
# Highest `?page=` a list accepts (50 rows each).
MAX_PAGE = 1000
# A budget at or below this share of its burst is shown as under pressure.
LOW_BUDGET = 0.2
MAX_SERVER_URL = 120
# Same length and alphabet as a real key (contracts/ids.md): sizes the QR before a key exists.
_SIZING_KEY = "utk_" + "A" * 43
QR_SCHEME = "ultimatetunes://connect"
# Per-user counter in the `settings` table; part of every session's fingerprint.
SESSION_EPOCH_KEY = ADMIN_EPOCH_PREFIX
# Fixed confirmation messages of `?done=`: nothing from the query string is ever echoed.
DONE = {
    "user_created": "User created.",
    "user_updated": "User updated.",
    "user_signed_out": "Every device of the user was signed out.",
    "key_revoked": "Key revoked.",
    "job_retried": "Download queued again.",
    "job_cancelled": "Cancel requested.",
    "track_deleted": "Track deleted.",
    "track_reviewed": "Marked as reviewed.",
    "album_deleted": "Album deleted.",
    "files_left": "Deleted, but some files could not be removed from disk (see the logs).",
    "command_queued": "Command queued: the next worker report picks it up.",
    "command_waiting": "That command is already waiting for a worker.",
    "notify_saved": "Notification settings saved.",
    "notify_sent": "Test notification sent.",
    "notify_failed": "The test notification could not be delivered.",
    "notify_rejected": (
        "ntfy rejected the credentials (HTTP 401 or 403). Check the access token, or the user"
        " and password, and that this user may write to the topic."
    ),
    "notify_rejected_webhook": "The webhook rejected the credentials (HTTP 401 or 403).",
    "disabled": "Two-factor authentication is off.",
}


# ---------------------------------------------------------------------- state and errors


@dataclass
class AdminState:
    """What the panel shares across requests (in `app.state.admin`). No request state here."""

    services: Services
    auth: AuthService
    codec: SessionCodec
    settings: AdminSettings
    templates: "Templates"
    sender: notify.Sender
    # Shown next to each user's usage, and in the overview (read once, like every setting).
    limits: DownloadLimits = field(default_factory=DownloadLimits)
    search: SearchSettings = field(default_factory=SearchSettings)


class Templates:
    def __init__(self) -> None:
        from jinja2 import Environment, PackageLoader, StrictUndefined  # noqa: PLC0415

        self.env = Environment(
            loader=PackageLoader("ultimatetunes", "templates/admin"),
            autoescape=True,
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.env.filters["size"] = human_size

    def render(self, name: str, context: Mapping[str, object]) -> str:
        return self.env.get_template(name).render(context)


def human_size(value: object) -> str:
    amount = float(value) if isinstance(value, int | float) else 0.0
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or unit == "TiB":  # noqa: PLR2004
            return f"{amount:.0f} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} TiB"  # pragma: no cover - the loop always returns


def state(request: Request) -> AdminState:
    found: AdminState = request.app.state.admin
    return found


class LoginRequired(Exception):  # noqa: N818 - a control-flow signal, not an error
    """No valid session: pages redirect to the login form, state changes get 403."""


class NotAdmin(Exception):  # noqa: N818
    """A valid session of a user who is not (or no longer) an admin."""


class CsrfRejected(Exception):  # noqa: N818
    """A state change without the session's CSRF token, or a cross-site one."""


@dataclass(frozen=True)
class Admin:
    user: User
    session: SessionData
    ip: str | None

    @property
    def principal(self) -> Principal:
        return Principal(self.user.id, self.user.username, "admin")


@dataclass(frozen=True)
class Posted:
    admin: Admin
    form: FormData

    def get(self, name: str) -> str:
        value = self.form.get(name)
        return value if isinstance(value, str) else ""


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def session_epoch(repo: AdminRepository, user_id: str) -> int:
    """The user's admin session epoch (0 until the first logout)."""
    raw = repo.setting(SESSION_EPOCH_KEY + user_id)
    try:
        return int(raw) if raw is not None else 0
    except ValueError:
        return 0


def lang_of(request: Request) -> Lang:
    return negotiate(request.headers.get("accept-language"))


def current_admin(request: Request) -> Admin:
    """The signed-in admin. Raises `LoginRequired` or `NotAdmin`."""
    st = state(request)
    cookie = request.cookies.get(SESSION_COOKIE)
    session = st.codec.read_session(cookie)
    if session is None:
        if cookie:
            session_rejected("invalid_or_expired")
        raise LoginRequired
    try:
        user = st.auth.get_user(session.user_id)
    except NotFound as exc:
        session_rejected("unknown_user")
        raise LoginRequired from exc
    if user.is_disabled:
        session_rejected("account_disabled", user.username)
        raise LoginRequired
    with st.services.db.read() as conn:
        epoch = session_epoch(AdminRepository(conn), user.id)
    if st.codec.fingerprint(user.password_hash, epoch) != session.fingerprint:
        session_rejected("revoked", user.username)
        raise LoginRequired
    if user.role != "admin":
        not_admin(user.username)
        raise NotAdmin
    return Admin(user, session, client_ip(request))


async def form_data(request: Request) -> FormData:
    return await request.form(max_files=0, max_fields=20)


def posted(
    request: Request,
    admin: Annotated[Admin, Depends(current_admin)],
    form: Annotated[FormData, Depends(form_data)],
) -> Posted:
    """A state change: an admin session, then the CSRF token (checked in that order)."""
    token = form.get(CSRF_FIELD)
    if not csrf_ok(request, admin.session.csrf, token if isinstance(token, str) else None):
        csrf_failure(request)
        raise CsrfRejected
    return Posted(admin, form)


AdminDep = Annotated[Admin, Depends(current_admin)]
PostedDep = Annotated[Posted, Depends(posted)]


def page(  # noqa: PLR0913 - the parts of one rendered page
    request: Request,
    template: str,
    context: Mapping[str, object] | None = None,
    *,
    admin: Admin | None = None,
    status: int = 200,
    error: str | None = None,
) -> HTMLResponse:
    lang = lang_of(request)
    _ = translator(lang)
    done = request.query_params.get("done")
    values: dict[str, object] = {
        "_": _,
        "lang": lang,
        "version": __version__,
        "admin": admin,
        "csrf": admin.session.csrf if admin else "",
        "path": request.url.path,
        "notice": _(DONE[done]) if done in DONE else None,
        "error": _(error) if error else None,
    }
    values.update(context or {})
    html = state(request).templates.render(template, values)
    return HTMLResponse(html, status_code=status)


def back(path: str, done: str) -> RedirectResponse:
    return RedirectResponse(f"{path}?done={done}", status_code=303)


@dataclass(frozen=True)
class Pager:
    """One page of a long list: `?page=N` (1-based), `PAGE_SIZE` rows, one extra row read to
    know whether a next page exists."""

    number: int
    has_next: bool
    # The other query parameters of the list (filters), kept by the page links.
    query: str = ""

    @staticmethod
    def wanted(request: Request) -> int:
        raw = request.query_params.get("page", "1")
        # ASCII digits only ("²" is a digit to `isdigit`), and short enough to never be huge.
        valid = raw.isascii() and raw.isdigit() and len(raw) <= len(str(MAX_PAGE))
        number = int(raw) if valid else 1
        return min(max(number, 1), MAX_PAGE)

    def href(self, number: int) -> str:
        return "?" + "&".join(p for p in (self.query, f"page={number}") if p)


def offset(number: int) -> int:
    """First row of page `number`."""
    return (number - 1) * PAGE_SIZE


def paged[T](rows: list[T], number: int, query: str = "") -> tuple[list[T], Pager]:
    """`rows` read with `PAGE_SIZE + 1` as limit: the page's rows and its pager."""
    return rows[:PAGE_SIZE], Pager(number, len(rows) > PAGE_SIZE, query)


def error_status(error: TunesError) -> int:
    if isinstance(error, NotFound):
        return 404
    if isinstance(error, Conflict):
        return 409
    return 400


def handlers() -> dict[type[Exception], object]:
    """Exception handlers `web.install` registers for the panel's own signals."""
    return {LoginRequired: _login_required, NotAdmin: _not_admin, CsrfRejected: _csrf_rejected}


async def _login_required(request: Request, _exc: Exception) -> Response:
    if request.method not in ("GET", "HEAD"):
        return _forbidden(request, "Your session has ended. Sign in again.")
    if request.headers.get("hx-request"):
        return Response(status_code=200, headers={"HX-Redirect": "/admin/login"})
    return RedirectResponse("/admin/login", status_code=303)


async def _not_admin(request: Request, _exc: Exception) -> Response:
    return _forbidden(request, "This account is not an administrator.")


async def _csrf_rejected(request: Request, _exc: Exception) -> Response:
    return _forbidden(request, "The form expired or came from another site. Reload and retry.")


def _forbidden(request: Request, message: str) -> Response:
    return page(
        request, "forbidden.html", {"message": translator(lang_of(request))(message)}, status=403
    )


# ---------------------------------------------------------------------- static


@router.get("/admin/static/{name}", include_in_schema=False)
def static(name: str) -> Response:
    found = STATIC_FILES.get(name)
    if found is None:
        return Response("Not found", status_code=404, media_type="text/plain")
    folder, media_type = found
    body = (resources.files("ultimatetunes") / "static" / folder / name).read_bytes()
    return Response(body, media_type=media_type, headers={"Cache-Control": "max-age=3600"})


# ---------------------------------------------------------------------- login and logout


@router.get("/admin/login", include_in_schema=False)
def login_form(request: Request) -> Response:
    return _login_page(request)


def _login_page(request: Request, *, error: str | None = None, status: int = 200) -> Response:
    cookie, token = state(request).codec.new_login_token()
    response = page(request, "login.html", {"login_token": token}, status=status, error=error)
    set_cookie(response, LOGIN_COOKIE, cookie, LOGIN_TTL_S)
    return response


@router.post("/admin/login", include_in_schema=False)
def login(  # noqa: PLR0911 - one return per outcome of the password step, plus the 2FA branch
    request: Request, form: Annotated[FormData, Depends(form_data)]
) -> Response:
    st = state(request)
    token = form.get(CSRF_FIELD)
    if request.headers.get("sec-fetch-site", "same-origin") not in (
        "same-origin",
        "none",
    ) or not st.codec.check_login_token(
        request.cookies.get(LOGIN_COOKIE), token if isinstance(token, str) else None
    ):
        csrf_failure(request, csrf_reason(request, "login_token"))
        return _forbidden(request, "The form expired or came from another site. Reload and retry.")
    username, password = form.get("username"), form.get("password")
    if not isinstance(username, str) or not isinstance(password, str) or not password:
        return _login_page(request, error="Wrong username or password.", status=400)
    ip = client_ip(request)
    try:
        user = st.auth.verify_password(username, password, ip, trusted=trusted_origin(request))
    except RateLimited:
        return _login_page(request, error="Too many attempts. Wait and try again.", status=429)
    except (AuthenticationFailed, AccountDisabled, Forbidden, InvalidParameter):
        return _login_page(request, error="Wrong username or password.", status=401)
    if user.role != "admin":
        not_admin(user.username)
        return _forbidden(request, "This account is not an administrator.")
    if st.auth.two_factor.is_enabled(user.id):
        # The password was right; hold the sign-in until the second factor (`/admin/login/2fa`).
        with st.services.db.read() as conn:
            epoch = session_epoch(AdminRepository(conn), user.id)
        cookie, pending = st.codec.new_pending_2fa(user.id, user.password_hash, epoch)
        response = _login_2fa_page(request, pending.csrf)
        set_cookie(response, PENDING_2FA_COOKIE, cookie, PENDING_2FA_TTL_S)
        clear_cookie(response, LOGIN_COOKIE)
        return response
    return _complete_login(request, user)


def _login_2fa_page(
    request: Request, csrf: str, *, error: str | None = None, status: int = 200
) -> Response:
    return page(request, "login_2fa.html", {"two_factor_csrf": csrf}, status=status, error=error)


def _complete_login(request: Request, user: User) -> Response:
    """Issues the admin session once every factor has passed, and audits the sign-in. An admin
    the require-policy covers but who has not enrolled is sent to the setup page."""
    st = state(request)
    ip = client_ip(request)
    with st.services.db.transaction() as conn:
        epoch = session_epoch(AdminRepository(conn), user.id)
        audit(conn, st.services.clock, actor_id=user.id, ip=ip, action="admin.login")
    cookie, _session = st.codec.new_session(user.id, user.password_hash, epoch)
    target = "/admin/2fa" if st.auth.two_factor.status(user.id, "admin").must_enroll else "/admin"
    response = RedirectResponse(target, status_code=303)
    set_cookie(response, SESSION_COOKIE, cookie, st.codec.ttl_s)
    clear_cookie(response, LOGIN_COOKIE)
    clear_cookie(response, PENDING_2FA_COOKIE)
    return response


@router.post("/admin/login/2fa", include_in_schema=False)
def login_second_factor(
    request: Request, form: Annotated[FormData, Depends(form_data)]
) -> Response:
    """The second step after a correct password: a TOTP code or a recovery code. The pending
    cookie proves the password step passed for this user (bound to the password fingerprint)."""
    st = state(request)
    pending = st.codec.read_pending_2fa(request.cookies.get(PENDING_2FA_COOKIE))
    token = form.get(CSRF_FIELD)
    if pending is None or not csrf_ok(
        request, pending.csrf, token if isinstance(token, str) else None
    ):
        csrf_failure(request, csrf_reason(request))
        return _login_page(request, error="Your sign-in expired. Start again.", status=403)
    try:
        user = st.auth.get_user(pending.user_id)
    except NotFound:
        return _login_page(request, error="Your sign-in expired. Start again.", status=403)
    with st.services.db.read() as conn:
        epoch = session_epoch(AdminRepository(conn), user.id)
    if (
        user.is_disabled
        or user.role != "admin"
        or st.codec.fingerprint(user.password_hash, epoch) != pending.fingerprint
    ):
        # The account changed (password, role, disabled) after the password step: start over.
        return _login_page(request, error="Your sign-in expired. Start again.", status=403)
    code = form.get("code")
    code_value = code if isinstance(code, str) else ""
    if not st.auth.two_factor.verify_second_factor(user.id, code_value, client_ip(request)):
        return _login_2fa_page(request, pending.csrf, error="That code is wrong.", status=401)
    return _complete_login(request, user)


@router.post("/admin/logout", include_in_schema=False)
def logout(request: Request, post: PostedDep) -> Response:
    st = state(request)
    user_id = post.admin.user.id
    with st.services.db.transaction() as conn:
        # Ends every session of this admin, copied cookies included (SECURITY.md, T22).
        repo = AdminRepository(conn)
        epoch = session_epoch(repo, user_id) + 1
        repo.put_setting(
            SESSION_EPOCH_KEY + user_id, str(epoch), format_ts(st.services.clock.now())
        )
        audit(conn, st.services.clock, actor_id=user_id, ip=post.admin.ip, action="admin.logout")
    response = RedirectResponse("/admin/login", status_code=303)
    clear_cookie(response, SESSION_COOKIE)
    return response


# ---------------------------------------------------------------------- two-factor


def _enrollment_qr(request: Request, uri: str) -> Markup:
    label = translator(lang_of(request))("QR code for your authenticator app")
    return qr.to_svg(qr.encode(uri), label=label)


def _two_factor_page(
    request: Request,
    admin: Admin,
    *,
    recovery: list[str] | None = None,
    error: str | None = None,
    status: int = 200,
) -> Response:
    tf = state(request).auth.two_factor
    status_data = tf.status(admin.user.id, "admin")
    pending = (
        None if status_data.enabled else tf.pending_enrollment(admin.user.id, admin.user.username)
    )
    context: dict[str, object] = {
        "status": status_data,
        "recovery": recovery,
        "qr": _enrollment_qr(request, pending.uri) if pending else None,
        "secret": pending.secret if pending else None,
    }
    return page(request, "two_factor.html", context, admin=admin, error=error, status=status)


@router.get("/admin/2fa", include_in_schema=False)
def two_factor_page(request: Request, admin: AdminDep) -> Response:
    return _two_factor_page(request, admin)


@router.post("/admin/2fa/enroll", include_in_schema=False)
def two_factor_enroll(request: Request, post: PostedDep) -> Response:
    """Starts (or restarts) the setup: a fresh secret, shown as a QR code to scan."""
    try:
        state(request).auth.two_factor.begin_enrollment(
            post.admin.user.id, post.admin.user.username
        )
    except TunesError as exc:
        return _two_factor_page(request, post.admin, error=exc.message, status=error_status(exc))
    return _two_factor_page(request, post.admin)


@router.post("/admin/2fa/confirm", include_in_schema=False)
def two_factor_confirm(request: Request, post: PostedDep) -> Response:
    """Confirms the setup with one code and reveals the recovery codes once."""
    try:
        recovery = state(request).auth.two_factor.confirm_enrollment(
            post.admin.user.id, post.get("code")
        )
    except TunesError as exc:
        return _two_factor_page(request, post.admin, error=exc.message, status=error_status(exc))
    return _two_factor_page(request, post.admin, recovery=recovery)


@router.post("/admin/2fa/disable", include_in_schema=False)
def two_factor_disable(request: Request, post: PostedDep) -> Response:
    """Turns the second factor off after the current password is re-entered."""
    st = state(request)
    if not _reauthenticate(st, post, request):
        return _two_factor_page(request, post.admin, error="The password is wrong.", status=401)
    try:
        st.auth.two_factor.disable(post.admin.user.id, "admin")
    except TunesError as exc:
        return _two_factor_page(request, post.admin, error=exc.message, status=error_status(exc))
    return back("/admin/2fa", "disabled")


@router.post("/admin/2fa/recovery", include_in_schema=False)
def two_factor_recovery(request: Request, post: PostedDep) -> Response:
    """Replaces the recovery codes after the current password is re-entered."""
    st = state(request)
    if not _reauthenticate(st, post, request):
        return _two_factor_page(request, post.admin, error="The password is wrong.", status=401)
    try:
        recovery = st.auth.two_factor.regenerate_recovery_codes(post.admin.user.id)
    except TunesError as exc:
        return _two_factor_page(request, post.admin, error=exc.message, status=error_status(exc))
    return _two_factor_page(request, post.admin, recovery=recovery)


def _reauthenticate(st: AdminState, post: Posted, request: Request) -> bool:
    """Checks the admin's current password for a sensitive 2FA change (disable, new codes)."""
    try:
        st.auth.verify_password(
            post.admin.user.username,
            post.get("password"),
            post.admin.ip,
            trusted=trusted_origin(request),
        )
    except TunesError:
        return False
    return True


# ---------------------------------------------------------------------- dashboard


@router.get("/admin", include_in_schema=False)
async def dashboard(request: Request, admin: AdminDep) -> Response:
    st = state(request)

    def read() -> dict[str, object]:
        services = st.services
        with services.db.read() as conn:
            repo = AdminRepository(conn)
            canaries = repo.canary_runs(1)
            usage = repo.user_usage(window_start(services.clock.now()))
            context: dict[str, object] = {
                "jobs": repo.job_counts(),
                "stats": repo.stats(),
                "canary": canaries[0] if canaries else None,
                "workers": repo.workers(),
                "users": len(st.auth.list_users()),
                "low_disk_since": repo.setting(LOW_DISK_KEY),
                "bytes_24h": sum(u.bytes_24h for u in usage.values()),
            }
        context["disks"] = disks(services, st.limits)
        context["limits"] = st.limits
        context["ytm_tokens"] = services.rate_limiter.peek(guard.BUCKET, ytm_limit(st.search))
        context["ytm_burst"] = st.search.ytm_burst
        return context

    context = await run_in_threadpool(read)
    context["breaker"] = await breaker(st.services)
    return page(request, "dashboard.html", context, admin=admin)


@dataclass(frozen=True)
class Disk:
    name: str
    free_bytes: int | None
    total_bytes: int | None
    low: bool


def disks(services: Services, limits: DownloadLimits) -> list[Disk]:
    """Free space of `/music` and `/staging` against `UT_MIN_FREE_BYTES` (unknown: low)."""
    found: list[Disk] = []
    for name, store in (("/music", services.library), ("/staging", services.staging)):
        try:
            usage = store.usage()
        except OSError:
            found.append(Disk(name, None, None, low=True))
            continue
        found.append(
            Disk(
                name, usage.free_bytes, usage.total_bytes, usage.free_bytes < limits.min_free_bytes
            )
        )
    return found


def ytm_limit(settings: SearchSettings) -> Limit:
    return Limit(settings.ytm_rate_per_s, settings.ytm_burst)


async def breaker(services: Services) -> object:
    catalog = services.catalog
    return await catalog.breaker_state() if isinstance(catalog, GuardedCatalog) else None


# ---------------------------------------------------------------------- users


@dataclass(frozen=True)
class Budget:
    """Tokens left of a per-user bucket, and whether that is low (`LOW_BUDGET`)."""

    left: int
    burst: int

    @property
    def low(self) -> bool:
        return self.left <= self.burst * LOW_BUDGET


def _users_page(
    request: Request, admin: Admin, *, error: str | None = None, status: int = 200
) -> Response:
    st = state(request)
    services = st.services
    users = st.auth.list_users()
    with services.db.read() as conn:
        usage = AdminRepository(conn).user_usage(window_start(services.clock.now()))
    catalog_limit = guard.user_limit(st.search)
    search_limit = Limit(st.search.search_user_rate_per_s, st.search.search_user_burst)
    limiter = services.rate_limiter

    def budget(key: str, limit: Limit) -> Budget:
        return Budget(int(limiter.peek(key, limit)), int(limit.burst))

    budgets = {
        u.id: (
            budget(guard.USER_BUCKET + u.id, catalog_limit),
            budget(search_service.USER_BUCKET + u.id, search_limit),
        )
        for u in users
    }
    context = {"users": users, "usage": usage, "budgets": budgets, "limits": st.limits}
    return page(request, "users.html", context, admin=admin, error=error, status=status)


@router.get("/admin/users", include_in_schema=False)
def users_page(request: Request, admin: AdminDep) -> Response:
    return _users_page(request, admin)


@router.post("/admin/users", include_in_schema=False)
def create_user(request: Request, post: PostedDep) -> Response:
    try:
        state(request).auth.create_user(
            post.get("username"),
            post.get("password"),
            post.get("role"),
            actor=post.admin.principal,
            client_ip=post.admin.ip,
        )
    except TunesError as exc:
        return _users_page(request, post.admin, error=exc.message, status=error_status(exc))
    return back("/admin/users", "user_created")


@router.post("/admin/users/{user_id}", include_in_schema=False)
def update_user(request: Request, user_id: str, post: PostedDep) -> Response:
    """`action`: `disable`, `enable`, `role` (with `role`), `password` (with `password`) or
    `sign_out` (with `confirm=yes`: every API key revoked and every admin and web session of
    the user ended, `AuthService.sign_out_everywhere`; for the admin's own account too, which
    then has to sign in again)."""
    auth = state(request).auth
    action = post.get("action")
    actor, ip = post.admin.principal, post.admin.ip
    try:
        if user_id == post.admin.user.id and action in ("disable", "role"):
            raise Conflict("You cannot disable yourself or change your own role")
        if action in ("disable", "enable"):
            auth.set_disabled(user_id, action == "disable", actor=actor, client_ip=ip)
        elif action == "role":
            auth.set_role(user_id, post.get("role"), actor=actor, client_ip=ip)
        elif action == "password":
            auth.set_password(user_id, post.get("password"), actor=actor, client_ip=ip)
        elif action == "sign_out":
            if post.get("confirm") != "yes":
                raise InvalidParameter("Tick the box to confirm signing out every device")
            auth.sign_out_everywhere(user_id, actor=actor, client_ip=ip)
        else:
            raise InvalidParameter("Unknown action")
    except TunesError as exc:
        return _users_page(request, post.admin, error=exc.message, status=error_status(exc))
    return back("/admin/users", "user_signed_out" if action == "sign_out" else "user_updated")


# ---------------------------------------------------------------------- API keys


def default_server_url(request: Request) -> str:
    """`UT_ADMIN_PUBLIC_URL`, else the address the browser used when it is https, else empty
    (the app needs https: an http address is never suggested)."""
    configured = state(request).settings.admin_public_url
    if configured:
        return configured
    base = str(request.base_url).rstrip("/")
    return base if base.startswith("https://") else ""


def check_server_url(url: str) -> str:
    cleaned = url.strip().rstrip("/")
    parts = urlsplit(cleaned)
    if (
        len(cleaned) > MAX_SERVER_URL
        or parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or not cleaned.isprintable()
        or " " in cleaned
    ):
        raise InvalidParameter("The server address must be an https URL of at most 120 characters")
    return cleaned


def connect_uri(server_url: str, key: str) -> str:
    """What the app's QR scanner reads: `ultimatetunes://connect?url=<server>&key=<api key>`."""
    return f"{QR_SCHEME}?url={quote(server_url, safe='')}&key={quote(key, safe='')}"


def _keys_page(
    request: Request,
    admin: Admin,
    *,
    error: str | None = None,
    status: int = 200,
    created: Mapping[str, object] | None = None,
) -> Response:
    auth = state(request).auth
    users = auth.list_users()
    names = {u.id: u.username for u in users}
    keys = sorted(
        (key for u in users for key in auth.list_keys(u.id)),
        key=lambda k: (k.revoked_at is not None, names[k.user_id], k.created_at),
    )
    context = {
        "users": users,
        "names": names,
        "keys": keys,
        "server_url": default_server_url(request),
        "created": created,
    }
    return page(request, "keys.html", context, admin=admin, error=error, status=status)


@router.get("/admin/keys", include_in_schema=False)
def keys_page(request: Request, admin: AdminDep) -> Response:
    return _keys_page(request, admin)


@router.post("/admin/keys", include_in_schema=False)
def create_key(request: Request, post: PostedDep) -> Response:
    """Shows the new key once, with its QR code; it is never stored or shown again. The QR is
    sized with a stand-in key first, so a failure never leaves a live key nobody saw."""
    try:
        server_url = check_server_url(post.get("server_url"))
        qr.choose_version(len(connect_uri(server_url, _SIZING_KEY).encode()))
        created = state(request).auth.create_key(
            post.get("user_id"),
            post.get("name"),
            actor=post.admin.principal,
            client_ip=post.admin.ip,
        )
        uri = connect_uri(server_url, created.secret)
        label = translator(lang_of(request))("QR code to connect the app")
        svg: Markup = qr.to_svg(qr.encode(uri), label=label)
    except (TunesError, qr.QrTooLongError) as exc:
        message = exc.message if isinstance(exc, TunesError) else "The server address is too long"
        return _keys_page(
            request,
            post.admin,
            error=message,
            status=400 if not isinstance(exc, TunesError) else error_status(exc),
        )
    shown = {
        "name": created.key.name,
        "secret": created.secret,
        "server_url": server_url,
        "qr": svg,
    }
    return _keys_page(request, post.admin, created=shown)


@router.post("/admin/keys/{key_id}/revoke", include_in_schema=False)
def revoke_key(request: Request, key_id: str, post: PostedDep) -> Response:
    try:
        state(request).auth.revoke_key(key_id, actor=post.admin.principal, client_ip=post.admin.ip)
    except TunesError as exc:
        return _keys_page(request, post.admin, error=exc.message, status=error_status(exc))
    return back("/admin/keys", "key_revoked")


# ---------------------------------------------------------------------- downloads queue


def _job_filter(request: Request) -> str | None:
    wanted = request.query_params.get("state")
    return wanted if wanted in JOB_STATES else None


def _jobs_context(request: Request) -> dict[str, object]:
    wanted = _job_filter(request)
    number = Pager.wanted(request)
    with state(request).services.db.read() as conn:
        repo = AdminRepository(conn)
        rows, pager = paged(
            repo.jobs(wanted, PAGE_SIZE + 1, offset(number)),
            number,
            f"state={wanted}" if wanted else "",
        )
        return {
            "jobs": rows,
            "pager": pager,
            "counts": repo.job_counts(),
            "states": JOB_STATES,
            "wanted": wanted,
        }


@router.get("/admin/jobs", include_in_schema=False)
def jobs_page(request: Request, admin: AdminDep) -> Response:
    return page(request, "jobs.html", _jobs_context(request), admin=admin)


@router.get("/admin/jobs/table", include_in_schema=False)
def jobs_table(request: Request, admin: AdminDep) -> Response:
    """The queue table alone, polled by HTMX every few seconds."""
    return page(request, "_jobs_table.html", _jobs_context(request), admin=admin)


def _jobs_error(request: Request, admin: Admin, exc: TunesError) -> Response:
    return page(
        request,
        "jobs.html",
        _jobs_context(request),
        admin=admin,
        error=exc.message,
        status=error_status(exc),
    )


@router.post("/admin/jobs/{job_id}/retry", include_in_schema=False)
def retry_job(request: Request, job_id: str, post: PostedDep) -> Response:
    """A failed or cancelled job goes back to the queue with its attempts reset."""
    services = state(request).services
    try:
        job = services.jobs.get(job_id)
        if job is None:
            raise NotFound("No such job")
        if job.state not in ("failed", "cancelled"):
            raise Conflict("Only failed or cancelled downloads can be retried")
        services.jobs.enqueue(
            track_id=job.track_id,
            video_id=job.yt_video_id,
            priority=max(job.priority, PRIORITY_KEEP),
            requested_by=post.admin.user.id,
        )
    except TunesError as exc:
        return _jobs_error(request, post.admin, exc)
    with services.db.transaction() as conn:
        audit(
            conn,
            services.clock,
            actor_id=post.admin.user.id,
            ip=post.admin.ip,
            action="job.retry",
            target_type="job",
            target_id=job_id,
        )
    return back("/admin/jobs", "job_retried")


@router.post("/admin/jobs/{job_id}/cancel", include_in_schema=False)
def cancel_job(request: Request, job_id: str, post: PostedDep) -> Response:
    services = state(request).services
    try:
        job = services.jobs.get(job_id)
        if job is None:
            raise NotFound("No such job")
        if job.state not in ("queued", "downloading", "tagging"):
            raise Conflict("Only queued or running downloads can be cancelled")
        services.jobs.request_cancel(job_id)
    except TunesError as exc:
        return _jobs_error(request, post.admin, exc)
    with services.db.transaction() as conn:
        audit(
            conn,
            services.clock,
            actor_id=post.admin.user.id,
            ip=post.admin.ip,
            action="job.cancel",
            target_type="job",
            target_id=job_id,
        )
    return back("/admin/jobs", "job_cancelled")


# ---------------------------------------------------------------------- library


def _library_page(
    request: Request, admin: Admin, *, error: str | None = None, status: int = 200
) -> Response:
    services = state(request).services
    query = request.query_params.get("q", "").strip()[:100]
    number = Pager.wanted(request)
    with services.db.read() as conn:
        repo = AdminRepository(conn)
        review, pager = paged(
            repo.needs_review(PAGE_SIZE + 1, offset(number)),
            number,
            f"q={quote(query)}" if query else "",
        )
        context: dict[str, object] = {
            "stats": repo.stats(),
            "review": review,
            "pager": pager,
            "low_disk_since": repo.setting(LOW_DISK_KEY),
            "query": query,
            "albums": repo.find_albums(query) if query else [],
            "tracks": repo.find_tracks(query) if query else [],
        }
    try:
        context["usage"] = services.library.usage()
    except OSError:
        context["usage"] = None
    return page(request, "library.html", context, admin=admin, error=error, status=status)


@router.get("/admin/library", include_in_schema=False)
def library_page(request: Request, admin: AdminDep) -> Response:
    return _library_page(request, admin)


@router.post("/admin/library/{kind}/{item_id}/delete", include_in_schema=False)
def delete_library_item(request: Request, kind: str, item_id: str, post: PostedDep) -> Response:
    """Deletes a track or an album. The rows (and the audit entry) are committed first; then
    the files go through `LibraryStore` (which removes a symlink itself, never its target), best
    effort: a file that cannot be removed is logged and left for the library scan, it never
    brings the rows back."""
    services = state(request).services
    try:
        if kind not in ("tracks", "albums"):
            raise NotFound("Not found")
        if post.get("confirm") != "yes":
            raise InvalidParameter("Tick the box to confirm the delete")
        with services.db.transaction() as conn:
            repo = AdminRepository(conn)
            deleted = repo.delete_track(item_id) if kind == "tracks" else repo.delete_album(item_id)
            audit(
                conn,
                services.clock,
                actor_id=post.admin.user.id,
                ip=post.admin.ip,
                action="track.delete" if kind == "tracks" else "album.delete",
                target_type=kind[:-1],
                target_id=item_id,
                detail={"tracks": deleted.tracks, "files": len(deleted.paths)},
            )
    except TunesError as exc:
        return _library_page(request, post.admin, error=exc.message, status=error_status(exc))
    left = 0
    for path in deleted.paths:
        try:
            services.library.delete(path)
        except (OSError, TunesError) as exc:
            left += 1
            log.warning(
                "library delete of %s %s: a file was left on disk (%s)",
                kind,
                item_id,
                type(exc).__name__,
            )
    if left:
        return back("/admin/library", "files_left")
    return back("/admin/library", "track_deleted" if kind == "tracks" else "album_deleted")


@router.post("/admin/library/tracks/{item_id}/reviewed", include_in_schema=False)
def mark_reviewed(request: Request, item_id: str, post: PostedDep) -> Response:
    """The admin checked a `needs_review` track (weak MusicBrainz match) and keeps its tags."""
    services = state(request).services
    try:
        with services.db.transaction() as conn:
            AdminRepository(conn).mark_reviewed(item_id, format_ts(services.clock.now()))
            audit(
                conn,
                services.clock,
                actor_id=post.admin.user.id,
                ip=post.admin.ip,
                action="track.review",
                target_type="track",
                target_id=item_id,
            )
    except TunesError as exc:
        return _library_page(request, post.admin, error=exc.message, status=error_status(exc))
    return back("/admin/library", "track_reviewed")


# ---------------------------------------------------------------------- yt-dlp and canary


@router.get("/admin/ytdlp", include_in_schema=False)
async def ytdlp_page(request: Request, admin: AdminDep) -> Response:
    st = state(request)

    def read() -> dict[str, object]:
        with st.services.db.read() as conn:
            repo = AdminRepository(conn)
            return {
                "workers": repo.workers(),
                "canaries": repo.canary_runs(),
                "commands": repo.commands(),
            }

    context = await run_in_threadpool(read)
    context["breaker"] = await breaker(st.services)
    return page(request, "ytdlp.html", context, admin=admin)


@router.post("/admin/ytdlp/{command}", include_in_schema=False)
def worker_command(request: Request, command: str, post: PostedDep) -> Response:
    """`update` (update yt-dlp now) or `canary` (run the canary now)."""
    services = state(request).services
    name = {"update": "update_ytdlp", "canary": "run_canary"}.get(command)
    if name is None or name not in WORKER_COMMANDS:
        return page(
            request,
            "forbidden.html",
            {"message": translator(lang_of(request))("Not found")},
            admin=post.admin,
            status=404,
        )
    with services.db.transaction() as conn:
        queued = AdminRepository(conn).add_command(name, post.admin.user.id, services.clock)
        if queued:
            audit(
                conn,
                services.clock,
                actor_id=post.admin.user.id,
                ip=post.admin.ip,
                action="worker.command",
                detail={"command": name},
            )
    return back("/admin/ytdlp", "command_queued" if queued else "command_waiting")


# ---------------------------------------------------------------------- audit log


@router.get("/admin/audit", include_in_schema=False)
def audit_page(request: Request, admin: AdminDep) -> Response:
    """Newest first, 50 per page, filtered by action and by who did it."""
    st = state(request)
    users = st.auth.list_users()
    names = {u.id: u.username for u in users}
    number = Pager.wanted(request)
    with st.services.db.read() as conn:
        repo = AdminRepository(conn)
        actions = repo.audit_actions()
        action = request.query_params.get("action", "")
        action = action if action in actions else ""
        actor = request.query_params.get("actor", "")
        actor = actor if actor in names else ""
        query = "&".join(
            f"{k}={quote(v, safe='')}" for k, v in (("action", action), ("actor", actor)) if v
        )
        rows, pager = paged(
            repo.audit_entries(action or None, actor or None, PAGE_SIZE + 1, offset(number)),
            number,
            query,
        )
    context = {
        "entries": [(entry, detail_text(entry.detail)) for entry in rows],
        "names": names,
        "users": users,
        "actions": actions,
        "action": action,
        "actor": actor,
        "pager": pager,
    }
    return page(request, "audit.html", context, admin=admin)


# ---------------------------------------------------------------------- notifications


def _notifications_page(
    request: Request, admin: Admin, *, error: str | None = None, status: int = 200
) -> Response:
    target = notify.load_target(state(request).services.db)
    sender = state(request).sender
    return page(
        request,
        "notifications.html",
        {
            "target": target,
            "kinds": notify.KINDS,
            "auth_kind": sender.auth_kind,
            "auth_host": sender.credentials_host,
            "auth_mismatch": target is not None
            and sender.auth_kind is not None
            and not sender.credentials_apply(target),
        },
        admin=admin,
        error=error,
        status=status,
    )


@router.get("/admin/notifications", include_in_schema=False)
def notifications_page(request: Request, admin: AdminDep) -> Response:
    return _notifications_page(request, admin)


@router.post("/admin/notifications", include_in_schema=False)
def save_notifications(request: Request, post: PostedDep) -> Response:
    services = state(request).services
    kind = post.get("kind")
    try:
        target = (
            None
            if kind == "none"
            else notify.Target(notify.check_kind(kind), notify.check_url(post.get("url")))
        )
    except TunesError as exc:
        return _notifications_page(request, post.admin, error=exc.message, status=error_status(exc))
    notify.save_target(services.db, services.clock, target)
    with services.db.transaction() as conn:
        # The URL may hold a private topic name: only the kind and host are audited.
        detail: dict[str, object] = (
            {"kind": target.kind, "host": target.host} if target else {"kind": "none"}
        )
        audit(
            conn,
            services.clock,
            actor_id=post.admin.user.id,
            ip=post.admin.ip,
            action="notify.update",
            detail=detail,
        )
    return back("/admin/notifications", "notify_saved")


@router.post("/admin/notifications/test", include_in_schema=False)
async def test_notification(request: Request, post: PostedDep) -> Response:
    st = state(request)
    target = await run_in_threadpool(notify.load_target, st.services.db)
    if target is None:
        return await run_in_threadpool(
            lambda: _notifications_page(
                request, post.admin, error="Set a notification target first", status=409
            )
        )
    message = notify.Message(
        "UltimateTunes test", "Notifications from your UltimateTunes server work."
    )
    outcome = await st.sender.deliver(target, message)

    def record() -> None:
        with st.services.db.transaction() as conn:
            audit(
                conn,
                st.services.clock,
                actor_id=post.admin.user.id,
                ip=post.admin.ip,
                action="notify.test",
                # Which kind of credentials went along, never their value.
                detail={
                    "kind": target.kind,
                    "host": target.host,
                    "auth": (st.sender.auth_kind or "none")
                    if st.sender.credentials_apply(target)
                    else "none",
                    "outcome": outcome,
                },
            )

    await run_in_threadpool(record)
    if outcome == "rejected":
        done = "notify_rejected" if target.kind == "ntfy" else "notify_rejected_webhook"
    else:
        done = "notify_sent" if outcome == "sent" else "notify_failed"
    return back("/admin/notifications", done)
