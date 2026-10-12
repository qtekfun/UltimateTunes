# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Search settings: the T03b defaults, read from `UT_*` variables."""

import pytest
from pydantic import ValidationError

from ultimatetunes.search.settings import SearchSettings


def test_defaults_follow_spec_section_11() -> None:
    s = SearchSettings()
    assert s.external_search
    assert s.search_external_timeout_s == 1.5
    assert (s.ytm_rate_per_s, s.ytm_burst, s.ytm_timeout_s) == (2.0, 6.0, 5.0)
    assert (s.ytm_breaker_base_s, s.ytm_breaker_max_s) == (300.0, 3600.0)
    assert s.ytm_location == ""


def test_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UT_EXTERNAL_SEARCH", "false")
    monkeypatch.setenv("UT_YTM_LOCATION", "ES")
    s = SearchSettings()
    assert not s.external_search
    assert s.ytm_location == "ES"
    monkeypatch.setenv("UT_YTM_LOCATION", "es; rm -rf")
    with pytest.raises(ValidationError):
        SearchSettings()
