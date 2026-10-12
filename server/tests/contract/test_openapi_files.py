# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The three OpenAPI contracts are valid OpenAPI 3.1 documents (PLAN T02, extended by T19)."""

from pathlib import Path

import pytest
from openapi_spec_validator import validate
from openapi_spec_validator.readers import read_from_filename

OPENAPI = Path(__file__).resolve().parents[3] / "contracts" / "openapi"
FILES = sorted(p.name for p in OPENAPI.glob("*.yaml"))


def test_all_three_contracts_are_present() -> None:
    assert FILES == ["internal-worker.yaml", "opensubsonic-subset.yaml", "ut-v1.yaml"]


@pytest.mark.parametrize("name", FILES)
def test_contract_is_valid_openapi(name: str) -> None:
    spec, _url = read_from_filename(str(OPENAPI / name))
    validate(spec)
