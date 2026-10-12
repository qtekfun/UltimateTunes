# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings of the web player: language, theme, the account (password, own API keys) and the
keyboard shortcuts.

- Language: a cookie (`LANG_COOKIE`, "en" or "es"; "auto" removes it and the browser decides).
- Theme: light, dark or the system's, kept by the browser only (`localStorage`, `theme.js`): a
  display preference, never sent to the server.
- Password: the current one is checked by `AuthService.verify_password` (its rate limit and
  lockout apply), the new one by the password policy. A new password ends every session of
  the user (web and admin) and every copied cookie; this browser gets a new session at once.
- API keys: the caller's own, listed and revoked through `AuthService` (`revoke_own_key`: a key
  of another user is `not_found`). Keys are created in the app or the admin panel, never here:
  a key is shown once and must not land in a browser page.

Confirmations are fixed messages chosen by `?done=<code>`: nothing from the query is echoed.
"""

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from ultimatetunes.core.forwarded import trusted_origin
from ultimatetunes.errors import (
    AccountDisabled,
    AuthenticationFailed,
    Forbidden,
    InvalidParameter,
    RateLimited,
)
from ultimatetunes.web.routes import (
    ItemId,
    Listener,
    ListenerDep,
    PostedDep,
    WebRoute,
    go,
    new_session_cookie,
    page,
    state,
)
from ultimatetunes.web.security import HOME, LANG_COOKIE, LANG_TTL_S, PREFIX

router = APIRouter(route_class=WebRoute)
SETTINGS = PREFIX + "/settings"
THEMES = (("system", "Same as the system"), ("light", "Light"), ("dark", "Dark"))
LANGUAGES = (("auto", "Same as the browser"), ("en", "English"), ("es", "Español"))
ERRORS = {
    "mismatch": "The new passwords do not match.",
    "attempts": "Too many attempts. Wait and try again.",
    "current": "The current password is wrong.",
    "policy": "The new password needs 12 to 1024 characters.",
}
DONE = {
    "password": "Password changed. Other devices were signed out.",  # nosec B105 - a message
    "key": "Key revoked.",
    "language": "Language saved.",
}


def _settings_page(
    request: Request, me: Listener, *, error: str | None = None, status: int = 200
) -> Response:
    keys = [k for k in state(request).auth.list_keys(me.user.id) if k.revoked_at is None]
    done = request.query_params.get("done")
    context = {
        "keys": keys,
        "notice": DONE.get(done or ""),
        "chosen_lang": request.cookies.get(LANG_COOKIE, "auto"),
        "themes": THEMES,
        "languages": LANGUAGES,
    }
    return page(request, "settings.html", context, listener=me, status=status, error=error)


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
    response = go(request, SETTINGS + "?done=password")
    new_session_cookie(response, request, auth.get_user(me.user.id))
    return response


@router.post(SETTINGS + "/keys/{id}/revoke", include_in_schema=False)
def revoke_key(request: Request, post: PostedDep, item_id: ItemId) -> Response:
    me = post.listener
    state(request).auth.revoke_own_key(me.principal, item_id, me.ip)
    return go(request, SETTINGS + "?done=key")
