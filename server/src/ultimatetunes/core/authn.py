# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Who is calling: `Principal`, and the `Authenticator` the routers call before a handler.

T04 implements `Authenticator` in `auth/` (API keys, key-as-password, the error 42/43/44 rules,
rate limit and lockout). Routers never parse credentials themselves: the OpenSubsonic pipeline
calls `authenticate_subsonic` for every non-public endpoint, and the `/ut/v1` routers depend
on `authenticate_api_key`. Each raises a `TunesError` (`AuthenticationRequired`,
`InvalidApiKey`, `RateLimited`, ...) on failure.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

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
