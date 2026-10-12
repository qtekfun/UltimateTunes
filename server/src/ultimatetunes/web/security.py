# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""How a browser proves who it is on the web player (`/` and `/web`), and the headers it gets.

The machinery is the admin panel's (`admin/security.py`, SPEC §11 T15), for any role:
- **Session**: a cookie signed with itsdangerous (`HttpOnly`, `Secure`, `SameSite=Strict`,
  `Path=/`, since the player is also the home page), stateless so any api replica can check
  it. It holds the user id, an expiry from the injected clock, the CSRF token and a fingerprint
  of the password hash and of the user's **web session epoch** (`web.session_epoch.<user id>`
  in the `settings` table, separate from the admin one). Changing the password ends every web
  session; signing out bumps the epoch, so copied cookies die too. Admin and web cookies use
  different salts: one is never the other.
- **CSRF**: every state change carries the session's token (form field `csrf`, or the
  `X-CSRF-Token` header that HTMX and `player.js` send) and must not be cross-site
  (`Sec-Fetch-Site`). The login form uses its own signed cookie with a token (double submit).
- No API key ever reaches the browser: media requests (`/web/stream`, `/web/cover`) use the
  session cookie too.

`WebGate` gives `/` and every `/web` response a strict CSP (scripts, styles, images and media
only from this server; no inline script or style, no framing), `nosniff`, `no-store` on pages
and no referrer; it caps request bodies and answers 404 under `/web` when the web player is
turned off. Unlike `/admin`, the player is not limited to the admin networks: it is a client
like the app.
"""

from itsdangerous import URLSafeSerializer
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ultimatetunes.admin.security import SessionCodec
from ultimatetunes.core.clock import Clock

PREFIX = "/web"
HOME = "/"
SESSION_COOKIE = "ut_web_session"
LOGIN_COOKIE = "ut_web_login"
# Per-user counter in the `settings` table; part of every web session's fingerprint.
EPOCH_KEY = "web.session_epoch."
MAX_BODY_BYTES = 64 * 1024

CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:;"
    " media-src 'self'; connect-src 'self'; form-action 'self'; frame-ancestors 'none';"
    " base-uri 'none'"
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
    "Permissions-Policy": (
        "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(),"
        " microphone=(), payment=(), usb=()"
    ),
}


def is_web_path(path: str) -> bool:
    return path in (HOME, PREFIX) or path.startswith(PREFIX + "/")


class WebSessionCodec(SessionCodec):
    """The admin codec with the web player's own salts."""

    def __init__(self, secret: str, clock: Clock, ttl_s: int) -> None:
        super().__init__(secret, clock, ttl_s)
        self._session = URLSafeSerializer(secret, salt="ultimatetunes.web.session")
        self._login = URLSafeSerializer(secret, salt="ultimatetunes.web.login")


class WebGate:
    """Security headers, body cap and on/off switch for `/web`. A plain ASGI middleware: every
    other path passes through untouched (no wrapping of `/rest` streams)."""

    def __init__(self, app: ASGIApp, *, enabled: bool = True) -> None:
        self._app = app
        self._enabled = enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not is_web_path(scope["path"]):
            await self._app(scope, receive, send)
            return
        refusal: Response | None = None
        if not self._enabled and scope["path"] != HOME:
            refusal = PlainTextResponse("Not found", status_code=404)
        elif too_big(Request(scope)):
            refusal = PlainTextResponse("Payload too large", status_code=413)
        if refusal is not None:
            for name, value in SECURITY_HEADERS.items():
                refusal.headers[name] = value
            await refusal(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    if name == "Cache-Control":
                        # Pages are never cached; covers and static files say their own lifetime.
                        headers.setdefault(name, value)
                    else:
                        headers[name] = value
            await send(message)

        await self._app(scope, receive, send_with_headers)


def too_big(request: Request) -> bool:
    length = request.headers.get("content-length")
    if length is None:
        # Browsers send forms with a length; a chunked body is refused rather than read unbounded.
        return "transfer-encoding" in request.headers
    try:
        return int(length) > MAX_BODY_BYTES
    except ValueError:
        return True


def set_cookie(response: Response, name: str, value: str, max_age: int) -> None:
    response.set_cookie(
        name, value, max_age=max_age, path=HOME, secure=True, httponly=True, samesite="strict"
    )


def clear_cookie(response: Response, name: str) -> None:
    response.delete_cookie(name, path=HOME, secure=True, httponly=True, samesite="strict")
