# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Users, API keys and authentication. Owned by PLAN T04 (100 % coverage).

T02 ships `build_authenticator` returning `PendingAuthenticator`, which refuses every
authenticated call with `FeatureNotImplemented`; T04 replaces it with the real
`core.authn.Authenticator` (API keys, key-as-password, errors 42/43/44, rate limit, lockout)
and fills `routes` (`/ut/v1/me`, `/ut/v1/keys`).
"""

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from ultimatetunes.core.authn import Authenticator, Principal
from ultimatetunes.errors import FeatureNotImplemented

if TYPE_CHECKING:
    from ultimatetunes.core.services import Services


class PendingAuthenticator:
    def authenticate_subsonic(
        self, params: Mapping[str, Sequence[str]], client_ip: str | None
    ) -> Principal:
        raise FeatureNotImplemented("Authentication is not implemented yet")

    def authenticate_api_key(
        self, header_key: str | None, query_key: str | None, client_ip: str | None
    ) -> Principal:
        raise FeatureNotImplemented("Authentication is not implemented yet")


def build_authenticator(services: "Services") -> Authenticator:
    return PendingAuthenticator()
