# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The admin panel's TOTP enrollment, the login second step and the require-policy."""

import re

from fastapi.testclient import TestClient

from tests.admin.conftest import People, csrf_of
from tests.auth.conftest import ADMIN_PASSWORD, fast_passwords
from ultimatetunes.auth import totp
from ultimatetunes.auth.service import AuthService
from ultimatetunes.auth.settings import AuthSettings
from ultimatetunes.core.clock import FakeClock

_SECRET = re.compile(r"<code>([A-Z2-7]+)</code>")


def _secret_on_page(html: str) -> str:
    found = _SECRET.search(html)
    assert found, "no secret shown on the setup page"
    return found.group(1)


def _code(clock: FakeClock, secret: str) -> str:
    return totp.code_at(secret, int(clock.now().timestamp()))


def enroll(client: TestClient, clock: FakeClock, csrf: str) -> list[str]:
    """Signs the admin through the whole setup and returns the recovery codes shown once."""
    setup = client.post("/admin/2fa/enroll", data={"csrf": csrf})
    assert setup.status_code == 200
    secret = _secret_on_page(setup.text)
    confirm = client.post("/admin/2fa/confirm", data={"csrf": csrf, "code": _code(clock, secret)})
    assert confirm.status_code == 200, confirm.text
    codes = re.findall(r"<li><code>([A-Z2-9-]+)</code></li>", confirm.text)
    assert len(codes) == totp.RECOVERY_CODE_COUNT
    return codes


def test_enroll_turns_two_factor_on(
    client: TestClient, people: People, admin_csrf: str, clock: FakeClock
) -> None:
    codes = enroll(client, clock, admin_csrf)
    assert len(set(codes)) == totp.RECOVERY_CODE_COUNT
    page = client.get("/admin/2fa")
    assert "is on for your account" in page.text


def test_confirm_with_a_wrong_code_stays_in_setup(
    client: TestClient, people: People, admin_csrf: str
) -> None:
    client.post("/admin/2fa/enroll", data={"csrf": admin_csrf})
    bad = client.post("/admin/2fa/confirm", data={"csrf": admin_csrf, "code": "000000"})
    assert bad.status_code == 409
    assert "Scan this code" in bad.text


def _login_password(client: TestClient) -> str:
    """Posts the password step for alice and returns the body (the 2FA page)."""
    form = client.get("/admin/login")
    r = client.post(
        "/admin/login",
        data={"csrf": csrf_of(form.text), "username": "alice", "password": ADMIN_PASSWORD},
    )
    assert r.status_code == 200, "an enabled account should land on the second step"
    return str(r.text)


def test_login_requires_the_second_factor(
    client: TestClient, people: People, admin_csrf: str, clock: FakeClock
) -> None:
    setup = client.post("/admin/2fa/enroll", data={"csrf": admin_csrf})
    secret = _secret_on_page(setup.text)
    client.post("/admin/2fa/confirm", data={"csrf": admin_csrf, "code": _code(clock, secret)})
    client.post("/admin/logout", data={"csrf": admin_csrf})
    body = _login_password(client)
    assert "Two-step verification" in body
    # Without the second factor the dashboard is still out of reach.
    assert client.get("/admin").status_code == 303
    clock.advance(totp.PERIOD_S)
    step = client.post(
        "/admin/login/2fa", data={"csrf": csrf_of(body), "code": _code(clock, secret)}
    )
    assert step.status_code == 303
    assert step.headers["location"] == "/admin"
    assert client.get("/admin").status_code == 200


def test_login_rejects_a_wrong_second_factor(
    client: TestClient, people: People, admin_csrf: str, clock: FakeClock
) -> None:
    setup = client.post("/admin/2fa/enroll", data={"csrf": admin_csrf})
    secret = _secret_on_page(setup.text)
    client.post("/admin/2fa/confirm", data={"csrf": admin_csrf, "code": _code(clock, secret)})
    client.post("/admin/logout", data={"csrf": admin_csrf})
    body = _login_password(client)
    bad = client.post("/admin/login/2fa", data={"csrf": csrf_of(body), "code": "000000"})
    assert bad.status_code == 401
    assert client.get("/admin").status_code == 303


def test_login_accepts_a_recovery_code(
    client: TestClient, people: People, admin_csrf: str, clock: FakeClock
) -> None:
    codes = enroll(client, clock, admin_csrf)
    client.post("/admin/logout", data={"csrf": admin_csrf})
    body = _login_password(client)
    step = client.post("/admin/login/2fa", data={"csrf": csrf_of(body), "code": codes[0]})
    assert step.status_code == 303
    assert client.get("/admin").status_code == 200


def test_disable_needs_the_password(
    client: TestClient, people: People, admin_csrf: str, clock: FakeClock
) -> None:
    enroll(client, clock, admin_csrf)
    tf = client.app.state.admin.auth.two_factor  # type: ignore[attr-defined]
    wrong = client.post(
        "/admin/2fa/disable", data={"csrf": admin_csrf, "password": "nope-nope-nope"}
    )
    assert wrong.status_code == 401
    assert tf.is_enabled(people.alice.id)
    good = client.post("/admin/2fa/disable", data={"csrf": admin_csrf, "password": ADMIN_PASSWORD})
    assert good.status_code == 303
    assert not tf.is_enabled(people.alice.id)


def test_required_admin_without_enrollment_is_sent_to_setup(
    client: TestClient, people: People, clock: FakeClock
) -> None:
    from ultimatetunes.core.services import Services  # noqa: PLC0415

    svc = client.app.state.admin.services  # type: ignore[attr-defined]
    assert isinstance(svc, Services)
    required = AuthService(
        svc.db,
        clock,
        svc.rate_limiter,
        AuthSettings(auth_require_2fa="admins"),
        fast_passwords(),
    )
    client.app.state.admin.auth = required  # type: ignore[attr-defined]
    form = client.get("/admin/login")
    r = client.post(
        "/admin/login",
        data={"csrf": csrf_of(form.text), "username": "alice", "password": ADMIN_PASSWORD},
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/2fa"


def test_regenerate_recovery_codes(
    client: TestClient, people: People, admin_csrf: str, clock: FakeClock
) -> None:
    old = enroll(client, clock, admin_csrf)
    r = client.post("/admin/2fa/recovery", data={"csrf": admin_csrf, "password": ADMIN_PASSWORD})
    assert r.status_code == 200
    fresh = re.findall(r"<li><code>([A-Z2-9-]+)</code></li>", r.text)
    assert set(fresh).isdisjoint(old)
