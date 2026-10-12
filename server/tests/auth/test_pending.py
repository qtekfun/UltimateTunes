# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`build_services` holds `PendingAuthenticator` only until the real one replaces it."""

import pytest

from ultimatetunes.auth import PendingAuthenticator, build_authenticator
from ultimatetunes.auth.service import AuthService
from ultimatetunes.core.services import build_services
from ultimatetunes.errors import FeatureNotImplemented
from ultimatetunes.settings import Settings


def test_services_get_the_real_authenticator(settings: Settings) -> None:
    services = build_services(settings)
    assert isinstance(services.authenticator, AuthService)
    assert isinstance(build_authenticator(services), AuthService)
    services.db.close()


def test_placeholder_refuses_everything() -> None:
    auth = PendingAuthenticator()
    with pytest.raises(FeatureNotImplemented):
        auth.authenticate_subsonic({"apiKey": ["utk_x"]}, "192.0.2.1")
    with pytest.raises(FeatureNotImplemented):
        auth.authenticate_api_key("utk_x", None, None)
