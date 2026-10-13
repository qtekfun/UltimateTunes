# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""YouTube account cookies: `/ut/v1/youtube-cookies` (D14). Owner: worker/cookies stream.

Admin-only, server-wide. The Android app (WebView login) or the admin panel PUTs the exported
Netscape `cookies.txt` as the request body; the api validates and stores it encrypted
(`youtube/cookies.py`). `GET .../status` returns only non-secret status; `DELETE` clears it.
A normal user's key gets 403; no key gets 401 (the router authenticates first). The body is
never logged; the audit entries (`youtube.cookies.set`/`.clear`) never carry the content.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response

from ultimatetunes.admin.repository import audit
from ultimatetunes.core.authn import Principal, current_principal
from ultimatetunes.core.services import Services, services
from ultimatetunes.errors import Forbidden, PayloadTooLarge
from ultimatetunes.youtube.cookies import CookieStatus, YouTubeCookieStore

router = APIRouter()
Caller = Annotated[Principal, Depends(current_principal)]


def _store(svc: Services) -> YouTubeCookieStore:
    return YouTubeCookieStore(svc.db, svc.clock)


def _require_admin(principal: Principal) -> None:
    # Only an admin's key may set or clear the server-wide YouTube session.
    if not principal.is_admin:
        raise Forbidden("Only an administrator may change the YouTube account")


def _status_json(status: CookieStatus, *, available: bool) -> dict[str, object]:
    return {
        "configured": status.configured,
        "setAt": status.set_at,
        "cookieCount": status.cookie_count,
        "hasYoutubeDomain": status.has_youtube_domain,
        "available": available,
    }


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/ut/v1/youtube-cookies/status")
async def youtube_cookies_status(request: Request, principal: Caller) -> Response:
    _require_admin(principal)
    store = _store(services(request))
    status = await run_in_threadpool(store.status)
    return JSONResponse(_status_json(status, available=store.available))


@router.put("/ut/v1/youtube-cookies")
async def set_youtube_cookies(request: Request, principal: Caller) -> Response:
    _require_admin(principal)
    svc = services(request)
    store = _store(svc)
    text = await _read_cookies(request, store.max_bytes)

    def store_and_audit() -> CookieStatus:
        status = store.set(text)  # validates; FeatureDisabled when no key is configured
        with svc.db.transaction() as conn:
            audit(
                conn,
                svc.clock,
                actor_id=principal.user_id,
                ip=_client_ip(request),
                action="youtube.cookies.set",
                # Non-secret only: how many cookies and whether a youtube.com one is present.
                detail={"count": status.cookie_count, "youtube": status.has_youtube_domain},
            )
        return status

    status = await run_in_threadpool(store_and_audit)
    return JSONResponse(_status_json(status, available=store.available))


@router.delete("/ut/v1/youtube-cookies")
async def clear_youtube_cookies(request: Request, principal: Caller) -> Response:
    _require_admin(principal)
    svc = services(request)
    store = _store(svc)

    def clear_and_audit() -> None:
        store.clear()
        with svc.db.transaction() as conn:
            audit(
                conn,
                svc.clock,
                actor_id=principal.user_id,
                ip=_client_ip(request),
                action="youtube.cookies.clear",
            )

    await run_in_threadpool(clear_and_audit)
    return JSONResponse(_status_json(CookieStatus(False), available=store.available))


async def _read_cookies(request: Request, max_bytes: int) -> str:
    """The request body as text, refusing anything over the cap. The body is never logged."""
    raw = await request.body()
    if len(raw) > max_bytes:
        raise PayloadTooLarge(f"The cookies file must be at most {max_bytes} bytes")
    return raw.decode("utf-8", "replace")
