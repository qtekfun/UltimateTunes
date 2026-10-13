# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The admin panel's YouTube account page (D14): status, manual paste and clear, audited
without the cookie content. Non-admin access, CSRF and login are covered by test_access.py."""

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from ultimatetunes.core.services import Services

COOKIE_VALUE = "EXAMPLE-invented-cookie-NOLEAK"
COOKIES = (
    f"# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t1999999999\tSID\t{COOKIE_VALUE}\n"
)


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UT_YTDLP_COOKIES_KEY", Fernet.generate_key().decode("ascii"))


def test_page_set_status_and_clear(client: TestClient, admin_csrf: str, services: Services) -> None:
    empty = client.get("/admin/youtube")
    assert empty.status_code == 200
    assert "No cookies set." in empty.text

    saved = client.post("/admin/youtube", data={"csrf": admin_csrf, "cookies": COOKIES})
    assert saved.status_code == 303

    page = client.get("/admin/youtube")
    assert "Cookies are set" in page.text
    assert COOKIE_VALUE not in page.text  # the status never shows the values

    cleared = client.post("/admin/youtube/clear", data={"csrf": admin_csrf})
    assert cleared.status_code == 303
    assert "No cookies set." in client.get("/admin/youtube").text

    with services.db.read() as conn:
        rows = conn.execute("SELECT action, detail FROM audit_log").fetchall()
    actions = {str(r["action"]) for r in rows}
    assert {"youtube.cookies.set", "youtube.cookies.clear"} <= actions
    assert all(COOKIE_VALUE not in str(r["detail"] or "") for r in rows)


def test_bad_cookies_show_an_error(client: TestClient, admin_csrf: str) -> None:
    r = client.post("/admin/youtube", data={"csrf": admin_csrf, "cookies": "nonsense"})
    assert r.status_code == 400
    assert "Netscape" in r.text
