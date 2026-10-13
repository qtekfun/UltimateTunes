# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`/ut/v1/youtube-cookies` (D14): admin-only set/clear/status, Netscape validation, and that
no cookie value leaks to the status response or the audit log. Invented cookies only."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.youtube.conftest import ADMIN_KEY, USER_KEY
from ultimatetunes.core.services import Services
from ultimatetunes.youtube.cookies import YouTubeCookieStore

pytestmark = pytest.mark.anyio

COOKIE_VALUE = "EXAMPLE-invented-cookie-NOLEAK"
COOKIES = (
    f"# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t1999999999\tSID\t{COOKIE_VALUE}\n"
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _admin(key: str = ADMIN_KEY) -> dict[str, str]:
    return {"X-Api-Key": key}


def test_status_requires_authentication(client: TestClient) -> None:
    assert client.get("/ut/v1/youtube-cookies/status").status_code == 401


def test_a_normal_user_is_forbidden(client: TestClient) -> None:
    assert (
        client.get("/ut/v1/youtube-cookies/status", headers={"X-Api-Key": USER_KEY}).status_code
        == 403
    )
    put = client.put("/ut/v1/youtube-cookies", content=COOKIES, headers={"X-Api-Key": USER_KEY})
    assert put.status_code == 403
    assert (
        client.delete("/ut/v1/youtube-cookies", headers={"X-Api-Key": USER_KEY}).status_code == 403
    )


def test_set_status_and_clear(client: TestClient, services: Services) -> None:
    assert (
        client.get("/ut/v1/youtube-cookies/status", headers=_admin()).json()["configured"] is False
    )

    put = client.put("/ut/v1/youtube-cookies", content=COOKIES, headers=_admin())
    assert put.status_code == 200
    body = put.json()
    assert (body["configured"], body["cookieCount"], body["hasYoutubeDomain"]) == (True, 1, True)

    # The decrypted cookies are really stored (through the encrypted store).
    store = YouTubeCookieStore(services.db, services.clock)
    assert store.current() == COOKIES

    status = client.get("/ut/v1/youtube-cookies/status", headers=_admin()).json()
    assert status["configured"] is True
    assert COOKIE_VALUE not in client.get("/ut/v1/youtube-cookies/status", headers=_admin()).text

    assert client.delete("/ut/v1/youtube-cookies", headers=_admin()).json()["configured"] is False
    assert store.current() is None


def test_bad_netscape_is_rejected(client: TestClient) -> None:
    r = client.put("/ut/v1/youtube-cookies", content="just some text", headers=_admin())
    assert r.status_code == 400
    assert r.json()["code"] == "invalid_parameter"


def test_too_large_is_refused(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UT_YTDLP_COOKIES_MAX_BYTES", "1024")
    body = COOKIES + ("# padding padding padding\n" * 200)
    r = client.put("/ut/v1/youtube-cookies", content=body, headers=_admin())
    assert r.status_code == 413


def test_without_a_key_the_feature_is_disabled(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("UT_YTDLP_COOKIES_KEY", raising=False)
    status = client.get("/ut/v1/youtube-cookies/status", headers=_admin()).json()
    assert status["available"] is False
    put = client.put("/ut/v1/youtube-cookies", content=COOKIES, headers=_admin())
    assert put.status_code == 409
    assert put.json()["code"] == "feature_disabled"


def test_set_and_clear_are_audited_without_the_content(
    client: TestClient, services: Services
) -> None:
    client.put("/ut/v1/youtube-cookies", content=COOKIES, headers=_admin())
    client.delete("/ut/v1/youtube-cookies", headers=_admin())
    with services.db.read() as conn:
        rows: list[Any] = conn.execute(
            "SELECT action, detail FROM audit_log ORDER BY occurred_at"
        ).fetchall()
    actions = [str(r["action"]) for r in rows]
    assert "youtube.cookies.set" in actions
    assert "youtube.cookies.clear" in actions
    assert all(COOKIE_VALUE not in str(r["detail"] or "") for r in rows)
