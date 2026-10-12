# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Who is calling: `Principal`, and the `Authenticator` the routers call before a handler.

T04 implements `Authenticator` in `auth/` (API keys, key-as-password, the error 42/43/44 rules,
rate limit and lockout). Routers never parse credentials themselves: the OpenSubsonic pipeline
calls `authenticate_subsonic` for every non-public endpoint, and the `/ut/v1` routers depend
on `authenticate_api_key`. Each raises a `TunesError` (`AuthenticationRequired`,
`InvalidApiKey`, `RateLimited`, ...) on failure.

`current_principal` is the FastAPI dependency that resolves the caller of an authenticated
`/ut/v1` route. It lives here (not in `ut/`) so area routes can depend on it, and reuse FastAPI's
per-request cache, without importing the router assembly.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from ultimatetunes.core.caller import set_caller

Role = Literal["admin", "user"]


@dataclass(frozen=True)
class Principal:
    user_id: str
    username: str
    role: Role
    api_key_id: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class Authenticator(Protocol):
    def authenticate_subsonic(
        self, params: Mapping[str, Sequence[str]], client_ip: str | None
    ) -> Principal:
        """OpenSubsonic credentials (`apiKey`, or `u` + `p`, `t`/`s` refused) from the merged
        query and form parameters."""
        ...

    def authenticate_api_key(
        self, header_key: str | None, query_key: str | None, client_ip: str | None
    ) -> Principal:
        """`/ut/v1`: `X-Api-Key` header or `apiKey` query parameter."""
        ...


async def current_principal(request: Request) -> Principal:
    """The caller of an authenticated `/ut/v1` route (cached per request by FastAPI)."""
    # Read from app state directly: `core.services` imports this module.
    authenticator: Authenticator = request.app.state.services.authenticator
    principal: Principal = await run_in_threadpool(
        authenticator.authenticate_api_key,
        request.headers.get("x-api-key"),
        request.query_params.get("apiKey"),
        request.client.host if request.client else None,
    )
    # Catalog lookups of this request are charged to its user (core/caller.py).
    set_caller(principal.user_id)
    return principal
