# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Languages of the panel, the vendored HTMX, and that the panel never loads anything from
another host (no CDN, scripts and styles only from `/admin/static`)."""

import hashlib
import re
from importlib import resources
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.admin.conftest import People
from ultimatetunes.admin import routes
from ultimatetunes.admin.catalog_es import ES
from ultimatetunes.admin.i18n import negotiate, translator
from ultimatetunes.admin.repository import JOB_STATES
from ultimatetunes.admin.security import CSP

PACKAGE = Path(str(resources.files("ultimatetunes")))
TEMPLATES = PACKAGE / "templates" / "admin"
STATIC = PACKAGE / "static" / "admin"
_MESSAGE = re.compile(r'_\("((?:[^"\\]|\\.)*)"')
_NAV = re.compile(r'\("/admin[^"]*", "([^"]+)"\)')


@pytest.mark.parametrize(
    ("header", "lang"),
    [
        (None, "en"),
        ("", "en"),
        ("es", "es"),
        ("es-ES,es;q=0.9,en;q=0.8", "es"),
        ("en-US,en;q=0.9,es;q=0.8", "en"),
        ("fr-FR,es;q=0.5", "es"),
        ("de", "en"),
        ("en;q=0.2,es;q=0.3", "es"),
        ("es;q=0", "en"),
        ("es;q=abc,en", "en"),
        ("es, en", "es"),
    ],
)
def test_negotiate(header: str | None, lang: str) -> None:
    assert negotiate(header) == lang


def test_translator() -> None:
    assert translator("en")("Version %(version)s", version="1.0") == "Version 1.0"
    assert translator("es")("Version %(version)s", version="1.0") == "Versión 1.0"
    assert translator("es")("Not in the catalog") == "Not in the catalog"


def _template_messages() -> set[str]:
    found: set[str] = set()
    for template in TEMPLATES.glob("*.html"):
        text = template.read_text(encoding="utf-8")
        found |= set(_MESSAGE.findall(text)) | set(_NAV.findall(text))
    return found


def test_every_message_has_a_spanish_translation() -> None:
    messages = _template_messages() | set(routes.DONE.values()) | set(JOB_STATES)
    missing = sorted(m for m in messages if m not in ES)
    assert not missing
    assert len(messages) > 100


def test_spanish_keeps_placeholders() -> None:
    for english, spanish in ES.items():
        assert re.findall(r"%\(\w+\)s", english) == re.findall(r"%\(\w+\)s", spanish)


def test_vendored_htmx_matches_its_record() -> None:
    record = (STATIC / "htmx.min.js.license").read_text(encoding="utf-8")
    digest = hashlib.sha256((STATIC / "htmx.min.js").read_bytes()).hexdigest()
    assert f"SHA-256: {digest}" in record
    assert "SPDX-License-Identifier: 0BSD" in record


def test_templates_and_styles_load_nothing_from_outside() -> None:
    for path in [*TEMPLATES.glob("*.html"), STATIC / "admin.css", STATIC / "admin.js"]:
        text = path.read_text(encoding="utf-8")
        for attribute in re.findall(r'(?:src|href|action|hx-get|hx-post)="([^"]*)"', text):
            assert attribute.startswith(("/", "{{", "#")) or attribute == "", (path.name, attribute)
        assert "@import" not in text
        assert "url(" not in text
        assert "<script>" not in text
        assert "style=" not in text
        assert " on" + "click" not in text


def test_pages_reference_only_local_assets(
    client: TestClient, admin_csrf: str, people: People
) -> None:
    page = client.get("/admin/users").text
    assert re.findall(r'<script[^>]*src="([^"]+)"', page) == [
        "/admin/static/htmx.min.js",
        "/admin/static/admin.js",
    ]
    assert re.findall(r'<link[^>]*href="([^"]+)"', page) == ["/admin/static/admin.css"]
    assert "//" not in "".join(re.findall(r'(?:src|href)="([^"]+)"', page))
    assert "script-src 'self'" in CSP
    assert "default-src 'none'" in CSP


def test_static_files(client: TestClient) -> None:
    js = client.get("/admin/static/htmx.min.js")
    assert js.status_code == 200
    assert js.headers["content-type"].startswith("text/javascript")
    assert js.content == (STATIC / "htmx.min.js").read_bytes()
    confirm = client.get("/admin/static/admin.js")
    assert confirm.headers["content-type"].startswith("text/javascript")
    assert "data-confirm" in confirm.text
    assert "eval(" not in confirm.text
    css = client.get("/admin/static/admin.css")
    assert css.headers["content-type"].startswith("text/css")
    for name in ("htmx.min.js.license", "../admin/routes.py", "nope.js"):
        assert client.get(f"/admin/static/{name}").status_code == 404
