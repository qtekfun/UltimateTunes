# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-area settings read their own `UT_*` variables (settings.py, AreaSettings)."""

import secrets

import pytest
from pydantic import ValidationError

from ultimatetunes.admin.settings import AdminSettings
from ultimatetunes.settings import AreaSettings, Settings
from ultimatetunes.streaming.settings import StreamingSettings


def test_streaming_caps_default_to_the_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    caps = StreamingSettings()
    assert (caps.max_listeners_per_job, caps.max_listeners_per_key) == (8, 4)
    monkeypatch.setenv("UT_MAX_LISTENERS_PER_JOB", "2")
    assert StreamingSettings().max_listeners_per_job == 2
    monkeypatch.setenv("UT_MAX_LISTENERS_PER_KEY", "0")
    with pytest.raises(ValidationError):
        StreamingSettings()


def test_area_settings_share_the_prefix_and_ignore_other_areas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UT_SOMETHING_OF_ANOTHER_AREA", "x")
    assert isinstance(AdminSettings(), AreaSettings)
    assert AreaSettings.model_config.get("env_prefix") == "UT_"


def test_refused_secrets_are_not_echoed_in_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every settings class hides the refused input (`settings_config`): a startup error
    must not print a token or password into the logs."""
    short = secrets.token_hex(8)  # too short for a worker token (32+)
    monkeypatch.setenv("UT_WORKER_TOKEN", short)
    with pytest.raises(ValidationError) as caught:
        Settings()
    assert "worker token" in str(caught.value)
    assert short not in str(caught.value)
    monkeypatch.setenv("UT_ADMIN_SESSION_SECRET", short)
    with pytest.raises(ValidationError) as admin:
        AdminSettings()
    assert short not in str(admin.value)
