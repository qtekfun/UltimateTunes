# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Who may use `/admin`, and how a browser proves it (CLAUDE.md security rules, SPEC §7).

In order, for every request under `/admin`:
1. **Network allowlist** (`AdminGate` middleware): the client address must be inside
   `UT_ADMIN_ALLOWED_NETWORKS` (LAN and Tailscale by default), otherwise 403 before anything
   else runs. The address is the one `core/forwarded.py` resolved (`X-Forwarded-For` only from
   `UT_TRUSTED_PROXIES`); a request with forwarding headers from any other peer, or a Tailscale
   Funnel request, is refused too: behind an unconfigured proxy every caller looks local.
   This is also the mitigation for the per-username lockout of T04 (SPEC §11): a stranger
   cannot reach the login form to lock an admin out.
2. **Session**: a cookie signed with itsdangerous (`HttpOnly`, `Secure`, `SameSite=Strict`,
   `Path=/admin`), stateless so any api replica can check it. It holds the user id, an expiry
   from the injected clock, the CSRF token and a fingerprint of the password hash and of the
   user's **session epoch** (changing the password ends every session; logging out bumps the
   epoch, kept in the `settings` table, so a copied cookie dies with the logout too). The
   user is read from the database on every request: a disabled user is logged out, a user who
   is not an admin gets 403.
3. **CSRF**: every state-changing request carries the session's token (form field `csrf`, or
   the `X-CSRF-Token` header that HTMX sends) and must not be cross-site (`Sec-Fetch-Site`).
   The login form uses its own signed cookie with a token (double submit).

Responses under `/admin` and `/` carry a strict CSP (scripts and styles only from this server,
nothing external), `no-store`, `nosniff`, no framing and no referrer.
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass

from itsdangerous import BadSignature, URLSafeSerializer
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ultimatetunes.admin.settings import IpNetwork
from ultimatetunes.core.clock import Clock
from ultimatetunes.core.forwarded import via_untrusted_proxy
from ultimatetunes.core.netaddr import in_networks

SESSION_COOKIE = "ut_admin_session"
LOGIN_COOKIE = "ut_admin_login"
COOKIE_PATH = "/admin"
CSRF_FIELD = "csrf"
CSRF_HEADER = "x-csrf-token"
LOGIN_TTL_S = 15 * 60
# Forms of the panel are small; anything bigger is refused before parsing.
MAX_BODY_BYTES = 64 * 1024
# Set by Tailscale Funnel on public requests: the panel is never served through Funnel.
FUNNEL_HEADER = "tailscale-funnel-request"

CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cross-Origin-Embedder-Policy": "require-corp",
    # The panel uses no browser feature beyond plain pages (ZAP baseline, T22).
    "Permissions-Policy": (
        "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(),"
        " microphone=(), payment=(), usb=()"
    ),
}


def is_admin_path(path: str) -> bool:
    return path == COOKIE_PATH or path.startswith(COOKIE_PATH + "/")


def client_allowed(host: str | None, networks: tuple[IpNetwork, ...]) -> bool:
    """True when `host` is an IP address inside one of `networks`. Hostnames, missing
    addresses and garbage are refused. IPv4-mapped IPv6 addresses count as IPv4."""
    return in_networks(host, networks)


class AdminGate:
    """Allowlist and body cap for `/admin`, security headers for `/admin` and `/`.

    A plain ASGI middleware: every other path passes through untouched (no wrapping of the
    streaming responses of `/rest`)."""

    def __init__(self, app: ASGIApp, networks: tuple[IpNetwork, ...]) -> None:
        self._app = app
        self._networks = networks

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        path: str = scope["path"]
        admin = is_admin_path(path)
        if not admin and path != "/":
            await self._app(scope, receive, send)
            return
        if admin:
            request = Request(scope)
            host = request.client.host if request.client else None
            refusal: Response | None = None
            if (
                not client_allowed(host, self._networks)
                or via_untrusted_proxy(scope)
                or FUNNEL_HEADER in request.headers
            ):
                refusal = PlainTextResponse("Forbidden", status_code=403)
            elif _too_big(request):
                refusal = PlainTextResponse("Payload too large", status_code=413)
            if refusal is not None:
                await _headers(refusal)(scope, receive, send)
                return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    if name == "Cache-Control":
                        # Pages are never cached; the two static files say their own lifetime.
                        headers.setdefault(name, value)
                    else:
                        headers[name] = value
            await send(message)

        await self._app(scope, receive, send_with_headers)


def _too_big(request: Request) -> bool:
    length = request.headers.get("content-length")
    if length is None:
        # Browsers send forms with a length; a chunked body is refused rather than read unbounded.
        return "transfer-encoding" in request.headers
    try:
        return int(length) > MAX_BODY_BYTES
    except ValueError:
        return True


def _headers(response: Response) -> Response:
    for name, value in SECURITY_HEADERS.items():
        response.headers[name] = value
    return response


@dataclass(frozen=True)
class SessionData:
    user_id: str
    csrf: str
    expires_at: int
    fingerprint: str


class SessionCodec:
    """Signs and checks the session and login cookies. Time from the injected clock."""

    def __init__(self, secret: str, clock: Clock, ttl_s: int) -> None:
        self._secret = secret.encode()
        self._clock = clock
        self.ttl_s = ttl_s
        self._session = URLSafeSerializer(secret, salt="ultimatetunes.admin.session")
        self._login = URLSafeSerializer(secret, salt="ultimatetunes.admin.login")

    def _now(self) -> int:
        return int(self._clock.now().timestamp())

    def fingerprint(self, password_hash: str, epoch: int = 0) -> str:
        """Changes whenever the password hash or the user's session epoch changes (logout
        bumps the epoch); reveals nothing about either."""
        message = f"{epoch}\x00{password_hash}".encode()
        return hmac.new(self._secret, message, hashlib.sha256).hexdigest()[:32]

    def new_session(
        self, user_id: str, password_hash: str, epoch: int = 0
    ) -> tuple[str, SessionData]:
        data = SessionData(
            user_id,
            secrets.token_urlsafe(32),
            self._now() + self.ttl_s,
            self.fingerprint(password_hash, epoch),
        )
        token = self._session.dumps([data.user_id, data.csrf, data.expires_at, data.fingerprint])
        return token, data

    def read_session(self, token: str | None) -> SessionData | None:
        if not token:
            return None
        try:
            value = self._session.loads(token)
        except BadSignature:
            return None
        if not _is_session_payload(value):
            return None
        data = SessionData(str(value[0]), str(value[1]), int(value[2]), str(value[3]))
        return data if data.expires_at > self._now() else None

    def new_login_token(self) -> tuple[str, str]:
        """(cookie value, form token) for the login form."""
        token = secrets.token_urlsafe(32)
        return self._login.dumps([token, self._now() + LOGIN_TTL_S]), token

    def check_login_token(self, cookie: str | None, submitted: str | None) -> bool:
        if not cookie or not submitted:
            return False
        try:
            value = self._login.loads(cookie)
        except BadSignature:
            return False
        if not (
            isinstance(value, list)
            and len(value) == 2  # noqa: PLR2004 - [token, expiry]
            and isinstance(value[0], str)
            and isinstance(value[1], int)
        ):
            return False
        return value[1] > self._now() and hmac.compare_digest(value[0], submitted)


def _is_session_payload(value: object) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 4  # noqa: PLR2004 - [user id, csrf, expiry, fingerprint]
        and isinstance(value[0], str)
        and isinstance(value[1], str)
        and isinstance(value[2], int)
        and isinstance(value[3], str)
    )


def csrf_ok(request: Request, expected: str, submitted: str | None) -> bool:
    """The token matches and the request is not cross-site."""
    if request.headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none"):
        return False
    token = submitted or request.headers.get(CSRF_HEADER)
    return bool(token) and hmac.compare_digest(str(token), expected)


def set_cookie(response: Response, name: str, value: str, max_age: int) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        path=COOKIE_PATH,
        secure=True,
        httponly=True,
        samesite="strict",
    )


def clear_cookie(response: Response, name: str) -> None:
    response.delete_cookie(name, path=COOKIE_PATH, secure=True, httponly=True, samesite="strict")
