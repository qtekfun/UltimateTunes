# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings of the web player: language, theme, the account (password, own API keys) and the
keyboard shortcuts.

- Language: a cookie (`LANG_COOKIE`, "en" or "es"; "auto" removes it and the browser decides).
- Theme: light, dark or the system's, kept by the browser only (`localStorage`, `theme.js`): a
  display preference, never sent to the server.
- Password: the current one is checked by `AuthService.verify_password` (its rate limit and
  lockout apply), the new one by the password policy. A new password ends every session of
  the user (web and admin) and every copied cookie; this browser gets a new session at once,
  and a full reload so the page carries the new session's CSRF token.
- API keys: the caller's own, listed and revoked through `AuthService` (`revoke_own_key`: a key
  of another user is `not_found`). Keys are created in the app or the admin panel, never here:
  a key is shown once and must not land in a browser page.
- Sign out every device: revokes every API key of the caller and ends every web and admin
  session of it, this one included (`AuthService.sign_out_everywhere`, audited). Only the
  caller's own account (no user id in the request), after ticking a confirmation box.

Confirmations are fixed messages chosen by `?done=<code>`: nothing from the query is echoed.
"""

from fastapi import APIRouter, Request
from markupsafe import Markup
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from ultimatetunes.admin import qr
from ultimatetunes.core.forwarded import trusted_origin
from ultimatetunes.errors import (
    AccountDisabled,
    AuthenticationFailed,
    Forbidden,
    InvalidParameter,
    RateLimited,
    TunesError,
)
from ultimatetunes.web.i18n import translator
from ultimatetunes.web.routes import (
    ItemId,
    Listener,
    ListenerDep,
    PostedDep,
    WebRoute,
    go,
    lang_of,
    new_session_cookie,
    page,
    state,
)
from ultimatetunes.web.security import HOME, LANG_COOKIE, LANG_TTL_S, PREFIX, SESSION_COOKIE

router = APIRouter(route_class=WebRoute)
SETTINGS = PREFIX + "/settings"
THEMES = (("system", "Same as the system"), ("light", "Light"), ("dark", "Dark"))
LANGUAGES = (("auto", "Same as the browser"), ("en", "English"), ("es", "Español"))
ERRORS = {
    "mismatch": "The new passwords do not match.",
    "attempts": "Too many attempts. Wait and try again.",
    "current": "The current password is wrong.",
    "policy": "The new password needs 12 to 1024 characters.",
    "confirm": "Tick the box to confirm signing out every device.",
}
DONE = {
    "password": "Password changed. Other devices were signed out.",  # nosec B105 - a message
    "key": "Key revoked.",
    "language": "Language saved.",
    "twofactor_off": "Two-factor authentication is off.",
}


def _two_factor_qr(request: Request, uri: str) -> Markup:
    label = translator(lang_of(request))("QR code for your authenticator app")
    return qr.to_svg(qr.encode(uri), label=label)


def _settings_page(
    request: Request,
    me: Listener,
    *,
    error: str | None = None,
    status: int = 200,
    recovery: list[str] | None = None,
) -> Response:
    st = state(request)
    keys = [k for k in st.auth.list_keys(me.user.id) if k.revoked_at is None]
    done = request.query_params.get("done")
    tf = st.auth.two_factor
    tf_status = tf.status(me.user.id, me.principal.role)
    pending = None if tf_status.enabled else tf.pending_enrollment(me.user.id, me.user.username)
    context = {
        "keys": keys,
        "notice": DONE.get(done or ""),
        "chosen_lang": request.cookies.get(LANG_COOKIE, "auto"),
        "themes": THEMES,
        "languages": LANGUAGES,
        "two_factor": tf_status,
        "tf_qr": _two_factor_qr(request, pending.uri) if pending else None,
        "tf_secret": pending.secret if pending else None,
        "tf_recovery": recovery,
    }
    return page(request, "settings.html", context, listener=me, status=status, error=error)


def _reauthenticate(request: Request, me: Listener, password: str) -> bool:
    try:
        state(request).auth.verify_password(
            me.user.username, password, me.ip, trusted=trusted_origin(request)
        )
    except TunesError:
        return False
    return True


@router.post(SETTINGS + "/2fa/enroll", include_in_schema=False)
def two_factor_enroll(request: Request, post: PostedDep) -> Response:
    """Starts (or restarts) the second-factor setup: a fresh secret shown as a QR code."""
    me = post.listener
    try:
        state(request).auth.two_factor.begin_enrollment(me.user.id, me.user.username)
    except TunesError as exc:
        return _settings_page(request, me, error=exc.message, status=400)
    return _settings_page(request, me)


@router.post(SETTINGS + "/2fa/confirm", include_in_schema=False)
def two_factor_confirm(request: Request, post: PostedDep) -> Response:
    """Confirms the setup with one code and reveals the recovery codes once."""
    me = post.listener
    try:
        recovery = state(request).auth.two_factor.confirm_enrollment(me.user.id, post.get("code"))
    except TunesError as exc:
        return _settings_page(request, me, error=exc.message, status=400)
    return _settings_page(request, me, recovery=recovery)


@router.post(SETTINGS + "/2fa/disable", include_in_schema=False)
def two_factor_disable(request: Request, post: PostedDep) -> Response:
    """Turns the second factor off after the current password is re-entered."""
    me = post.listener
    if not _reauthenticate(request, me, post.get("password")):
        return _settings_page(request, me, error=ERRORS["current"], status=400)
    try:
        state(request).auth.two_factor.disable(me.user.id, me.principal.role)
    except TunesError as exc:
        return _settings_page(request, me, error=exc.message, status=400)
    return go(request, SETTINGS + "?done=twofactor_off")


@router.post(SETTINGS + "/2fa/recovery", include_in_schema=False)
def two_factor_recovery(request: Request, post: PostedDep) -> Response:
    """Replaces the recovery codes after the current password is re-entered."""
    me = post.listener
    if not _reauthenticate(request, me, post.get("password")):
        return _settings_page(request, me, error=ERRORS["current"], status=400)
    try:
        recovery = state(request).auth.two_factor.regenerate_recovery_codes(me.user.id)
    except TunesError as exc:
        return _settings_page(request, me, error=exc.message, status=400)
    return _settings_page(request, me, recovery=recovery)


@router.get(SETTINGS, include_in_schema=False)
async def settings_page(request: Request, me: ListenerDep) -> Response:
    return await run_in_threadpool(_settings_page, request, me)


@router.post(SETTINGS + "/language", include_in_schema=False)
def set_language(request: Request, post: PostedDep) -> Response:
    lang = post.get("lang")
    if lang not in ("en", "es", "auto"):
        raise InvalidParameter("Unknown language")
    # A full reload: the whole shell (navigation, player) changes language.
    if request.headers.get("hx-request"):
        response = Response(status_code=200, headers={"HX-Redirect": SETTINGS + "?done=language"})
    else:
        response = Response(status_code=303, headers={"Location": SETTINGS + "?done=language"})
    if lang == "auto":
        response.delete_cookie(
            LANG_COOKIE, path=HOME, secure=True, httponly=True, samesite="strict"
        )
    else:
        response.set_cookie(
            LANG_COOKIE,
            lang,
            max_age=LANG_TTL_S,
            path=HOME,
            secure=True,
            httponly=True,
            samesite="strict",
        )
    return response


@router.post(SETTINGS + "/password", include_in_schema=False)
def change_password(request: Request, post: PostedDep) -> Response:
    me = post.listener
    current, new, again = post.get("current"), post.get("new"), post.get("confirm")
    if new != again:
        return _settings_page(request, me, error=ERRORS["mismatch"], status=400)
    auth = state(request).auth
    try:
        auth.verify_password(me.user.username, current, me.ip, trusted=trusted_origin(request))
    except RateLimited:
        return _settings_page(request, me, error=ERRORS["attempts"], status=429)
    except (AuthenticationFailed, AccountDisabled, Forbidden, InvalidParameter):
        return _settings_page(request, me, error=ERRORS["current"], status=400)
    try:
        auth.set_password(me.user.id, new, actor=me.principal, client_ip=me.ip)
    except InvalidParameter:
        return _settings_page(request, me, error=ERRORS["policy"], status=400)
    # A full reload, not an HTMX swap: the page must pick up the new session's CSRF token.
    target = SETTINGS + "?done=password"
    if request.headers.get("hx-request"):
        response = Response(status_code=200, headers={"HX-Redirect": target})
    else:
        response = Response(status_code=303, headers={"Location": target})
    new_session_cookie(response, request, auth.get_user(me.user.id))
    return response


@router.post(SETTINGS + "/keys/{id}/revoke", include_in_schema=False)
def revoke_key(request: Request, post: PostedDep, item_id: ItemId) -> Response:
    me = post.listener
    state(request).auth.revoke_own_key(me.principal, item_id, me.ip)
    return go(request, SETTINGS + "?done=key")


@router.post(SETTINGS + "/sign-out-everywhere", include_in_schema=False)
def sign_out_everywhere(request: Request, post: PostedDep) -> Response:
    me = post.listener
    if post.get("confirm") != "yes":
        return _settings_page(request, me, error=ERRORS["confirm"], status=400)
    state(request).auth.sign_out_everywhere(me.user.id, actor=me.principal, client_ip=me.ip)
    # This session ended too: back to the sign-in form, with a full reload.
    if request.headers.get("hx-request"):
        response = Response(status_code=200, headers={"HX-Redirect": HOME})
    else:
        response = Response(status_code=303, headers={"Location": HOME})
    response.delete_cookie(SESSION_COOKIE, path=HOME, secure=True, httponly=True, samesite="strict")
    return response
