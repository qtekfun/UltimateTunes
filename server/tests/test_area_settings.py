# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-area settings read their own `UT_*` variables (settings.py, AreaSettings)."""

import pytest
from pydantic import ValidationError

from ultimatetunes.admin.settings import AdminSettings
from ultimatetunes.settings import AreaSettings
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
