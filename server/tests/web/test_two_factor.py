# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The web player's TOTP enrollment in Settings and the login second step."""

import re

from fastapi.testclient import TestClient

from tests.auth.conftest import TOTP_KEY, fast_passwords
from tests.web.conftest import People, csrf_of
from ultimatetunes.auth import totp
from ultimatetunes.auth.service import AuthService
from ultimatetunes.auth.settings import AuthSettings
from ultimatetunes.core.clock import FakeClock

_SECRET = re.compile(r"<code>([A-Z2-7]{16,})</code>")
_RECOVERY = re.compile(r"<li><code>([A-Z2-9-]+)</code></li>")


def _code(clock: FakeClock, secret: str) -> str:
    return totp.code_at(secret, int(clock.now().timestamp()))


def _secret_on_page(html: str) -> str:
    found = _SECRET.search(html)
    assert found, "no TOTP secret on the settings page"
    return found.group(1)


def enroll(client: TestClient, clock: FakeClock, csrf: str) -> tuple[str, list[str]]:
    setup = client.post("/web/settings/2fa/enroll", data={"csrf": csrf})
    assert setup.status_code == 200
    secret = _secret_on_page(setup.text)
    confirm = client.post(
        "/web/settings/2fa/confirm", data={"csrf": csrf, "code": _code(clock, secret)}
    )
    assert confirm.status_code == 200, confirm.text
    codes = _RECOVERY.findall(confirm.text)
    assert len(codes) == totp.RECOVERY_CODE_COUNT
    return secret, codes


def test_enroll_turns_two_factor_on(
    client: TestClient, people: People, ana: str, clock: FakeClock
) -> None:
    _secret, codes = enroll(client, clock, ana)
    assert len(set(codes)) == totp.RECOVERY_CODE_COUNT
    assert "is on" in client.get("/web/settings").text


def _password_step(client: TestClient, account: object) -> str:
    form = client.get("/web/login")
    r = client.post(
        "/web/login",
        data={
            "csrf": csrf_of(form.text),
            "username": account.user.username,  # type: ignore[attr-defined]
            "password": account.password,  # type: ignore[attr-defined]
        },
    )
    assert r.status_code == 200, "an enabled account should land on the second step"
    return str(r.text)


def test_login_requires_the_second_factor(
    client: TestClient, people: People, ana: str, clock: FakeClock
) -> None:
    secret, _codes = enroll(client, clock, ana)
    client.post("/web/logout", data={"csrf": ana})
    body = _password_step(client, people.ana)
    assert "Two-step verification" in body
    clock.advance(totp.PERIOD_S)
    step = client.post("/web/login/2fa", data={"csrf": csrf_of(body), "code": _code(clock, secret)})
    assert step.status_code == 303
    assert step.headers["location"] == "/"


def test_login_rejects_a_wrong_code(
    client: TestClient, people: People, ana: str, clock: FakeClock
) -> None:
    enroll(client, clock, ana)
    client.post("/web/logout", data={"csrf": ana})
    body = _password_step(client, people.ana)
    bad = client.post("/web/login/2fa", data={"csrf": csrf_of(body), "code": "000000"})
    assert bad.status_code == 401


def test_login_accepts_a_recovery_code(
    client: TestClient, people: People, ana: str, clock: FakeClock
) -> None:
    _secret, codes = enroll(client, clock, ana)
    client.post("/web/logout", data={"csrf": ana})
    body = _password_step(client, people.ana)
    step = client.post("/web/login/2fa", data={"csrf": csrf_of(body), "code": codes[0]})
    assert step.status_code == 303


def test_disable_needs_the_password(
    client: TestClient, people: People, ana: str, clock: FakeClock
) -> None:
    enroll(client, clock, ana)
    auth = client.app.state.web.auth  # type: ignore[attr-defined]
    wrong = client.post(
        "/web/settings/2fa/disable", data={"csrf": ana, "password": "wrong-wrong-wrong"}
    )
    assert wrong.status_code == 400
    assert auth.two_factor.is_enabled(people.ana.user.id)
    # A wrong password from outside starts a short backoff; let it pass before the real one.
    clock.advance(10)
    good = client.post(
        "/web/settings/2fa/disable", data={"csrf": ana, "password": people.ana.password}
    )
    assert good.status_code == 303
    assert not auth.two_factor.is_enabled(people.ana.user.id)


def test_required_user_is_gated_until_enrolled(
    client: TestClient, people: People, clock: FakeClock
) -> None:
    svc = client.app.state.web.services  # type: ignore[attr-defined]
    required = AuthService(
        svc.db,
        clock,
        svc.rate_limiter,
        AuthSettings(auth_require_2fa="all", totp_encryption_key=TOTP_KEY),
        fast_passwords(),
    )
    client.app.state.web.auth = required  # type: ignore[attr-defined]
    form = client.get("/web/login")
    r = client.post(
        "/web/login",
        data={
            "csrf": csrf_of(form.text),
            "username": people.ana.user.username,
            "password": people.ana.password,
        },
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/web/settings"
    # A protected page is refused and points at Settings; Settings itself is reachable.
    blocked = client.get("/web/library")
    assert blocked.status_code == 303
    assert blocked.headers["location"] == "/web/settings"
    settings = client.get("/web/settings")
    assert settings.status_code == 200
    csrf = csrf_of(settings.text)
    started = client.post("/web/settings/2fa/enroll", data={"csrf": csrf})
    secret = _secret_on_page(started.text)
    client.post("/web/settings/2fa/confirm", data={"csrf": csrf, "code": _code(clock, secret)})
    # After enrolling, the rest of the player opens up.
    assert client.get("/web/library").status_code == 200
