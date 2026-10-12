# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Until T04 lands, every authenticated call is refused as not implemented."""

import pytest

from ultimatetunes.auth import PendingAuthenticator, build_authenticator
from ultimatetunes.core.services import build_services
from ultimatetunes.errors import FeatureNotImplemented
from ultimatetunes.settings import Settings


def test_pending_authenticator_refuses_everything(settings: Settings) -> None:
    services = build_services(settings)
    auth = build_authenticator(services)
    assert isinstance(auth, PendingAuthenticator)
    with pytest.raises(FeatureNotImplemented):
        auth.authenticate_subsonic({"apiKey": ["utk_x"]}, "192.0.2.1")
    with pytest.raises(FeatureNotImplemented):
        auth.authenticate_api_key("utk_x", None, None)
    services.db.close()
