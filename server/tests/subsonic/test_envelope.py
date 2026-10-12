# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The envelope renders every contract example: XML examples are `to_xml` of the JSON ones."""

from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]  # dev-only, via schemathesis

from ultimatetunes.errors import FeatureNotImplemented, InvalidApiKey, NotFound, RateLimited
from ultimatetunes.subsonic.envelope import envelope, render_error, to_xml

CONTRACT = (
    Path(__file__).resolve().parents[3] / "contracts" / "openapi" / "opensubsonic-subset.yaml"
)
EXAMPLES: dict[str, Any] = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))["components"][
    "examples"
]
PAIRS = sorted(name for name in EXAMPLES if f"{name}_xml" in EXAMPLES)


@pytest.mark.parametrize("name", PAIRS)
def test_xml_examples_follow_the_mapping_rule(name: str) -> None:
    assert to_xml(EXAMPLES[name]["value"]) == EXAMPLES[f"{name}_xml"]["value"]


def test_every_example_has_a_pair() -> None:
    assert len(PAIRS) * 2 == len(EXAMPLES)


def test_escaping_and_illegal_characters() -> None:
    doc = envelope({"song": {"title": 'A & B <"C">\x01', "line": [{"start": 0, "value": "x<y"}]}})
    xml = to_xml(doc)
    assert 'title="A &amp; B &lt;&quot;C&quot;&gt;"' in xml
    assert '<line start="0">x&lt;y</line>' in xml


def test_unmappable_values_are_refused() -> None:
    with pytest.raises(TypeError, match="cannot map"):
        to_xml(envelope({"song": {"bad": [object()]}}))
    with pytest.raises(TypeError, match="object"):
        to_xml({"subsonic-response": "nope"})


def test_failed_envelope_and_statuses() -> None:
    doc = envelope(error=InvalidApiKey(help_url="https://music.example.net/admin/keys"))
    body = doc["subsonic-response"]
    assert isinstance(body, dict)
    assert body["status"] == "failed"
    assert body["error"] == {
        "code": 44,
        "message": "Invalid API key",
        "helpUrl": "https://music.example.net/admin/keys",
    }
    assert render_error(NotFound(), "json").status_code == 200
    assert render_error(FeatureNotImplemented(), "xml").status_code == 501
    limited = render_error(RateLimited(30), "json")
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "30"
