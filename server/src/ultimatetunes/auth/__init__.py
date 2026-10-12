# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Users, API keys and authentication. Owned by PLAN T04 (100 % coverage).

`build_authenticator` gives `core.services` the real `core.authn.Authenticator`: an
`AuthService` (`service.py`: API keys, key as password, errors 10/40/42/43/44/50, rate limit
and lockout, audit log). `PendingAuthenticator` is only the placeholder `build_services` holds
while it builds the services the real one needs.
"""

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from ultimatetunes.core.authn import Authenticator, Principal
from ultimatetunes.errors import FeatureNotImplemented

if TYPE_CHECKING:
    from ultimatetunes.core.services import Services


class PendingAuthenticator:
    """Refuses every call: in place only until `build_authenticator` replaces it."""

    def authenticate_subsonic(
        self, params: Mapping[str, Sequence[str]], client_ip: str | None
    ) -> Principal:
        raise FeatureNotImplemented("Authentication is not ready yet")

    def authenticate_api_key(
        self, header_key: str | None, query_key: str | None, client_ip: str | None
    ) -> Principal:
        raise FeatureNotImplemented("Authentication is not ready yet")


def build_authenticator(services: "Services") -> Authenticator:
    from ultimatetunes.auth.service import AuthService  # noqa: PLC0415 - avoids an import cycle

    return AuthService.from_services(services)
