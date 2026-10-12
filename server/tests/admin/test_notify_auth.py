# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Credentials of the notification target (ntfy behind login): an access token as Bearer, or a
user and password as Basic, only from the environment or Docker secrets. They go only on the
request to the configured https URL, never after a redirect, and never reach logs, the audit
log or the page. Secrets here are made at run time."""

import asyncio
import base64
import logging
import secrets
import string
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from tests.admin.conftest import SECRET, RecordingTransport, public_dns
from ultimatetunes.admin import web
from ultimatetunes.admin.notify import Credentials, Message, Outcome, Sender, Target
from ultimatetunes.admin.settings import AdminSettings, host_and_port
from ultimatetunes.core.services import Services

HOST = "ntfy.example.com"
NTFY = f"https://{HOST}/ut-alerts"
MESSAGE = Message("t", "b")


def ntfy_token() -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "tk_" + "".join(secrets.choice(alphabet) for _ in range(29))


def password() -> str:
    return secrets.token_urlsafe(18)


def _deliver(sender: Sender, target: Target) -> Outcome:
    return asyncio.run(sender.deliver(target, MESSAGE))


def _settings(**values: str) -> AdminSettings:
    return AdminSettings(
        admin_session_secret=SecretStr(SECRET),
        notify_host=HOST,
        **{k: SecretStr(v) for k, v in values.items()},  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------- settings


@pytest.fixture(autouse=True)
def _environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """No credentials from the machine running the tests; the bound host is set."""
    for name in ("TOKEN", "USERNAME", "PASSWORD"):
        monkeypatch.delenv(f"UT_NOTIFY_{name}", raising=False)
    monkeypatch.setenv("UT_NOTIFY_HOST", HOST)


def test_no_credentials_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("UT_NOTIFY_TOKEN", "UT_NOTIFY_USERNAME", "UT_NOTIFY_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    assert Credentials.from_settings(AdminSettings()) is None
    # Blank values (an empty secret file, `UT_NOTIFY_TOKEN=`) mean unset.
    assert Credentials.from_settings(_settings(notify_token="  ")) is None


def test_token_from_env_and_from_a_docker_secret(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from_file, from_env = ntfy_token(), ntfy_token()
    (tmp_path / "ut_notify_token").write_text(from_file + "\n", encoding="utf-8")
    monkeypatch.delenv("UT_NOTIFY_TOKEN", raising=False)
    secret_only = AdminSettings(_secrets_dir=tmp_path)
    credentials = Credentials.from_settings(secret_only)
    assert credentials is not None
    assert credentials.kind == "token"
    assert credentials.authorization.get_secret_value() == f"Bearer {from_file}"
    # The env var wins over the secret file (pydantic-settings' order).
    monkeypatch.setenv("UT_NOTIFY_TOKEN", from_env)
    both = Credentials.from_settings(AdminSettings(_secrets_dir=tmp_path))
    assert both is not None
    assert both.authorization.get_secret_value() == f"Bearer {from_env}"


def test_user_and_password_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = password()
    monkeypatch.setenv("UT_NOTIFY_USERNAME", "alerts")
    monkeypatch.setenv("UT_NOTIFY_PASSWORD", secret)
    credentials = Credentials.from_settings(AdminSettings())
    assert credentials is not None
    assert credentials.kind == "basic"
    scheme, encoded = credentials.authorization.get_secret_value().split(" ")
    assert scheme == "Basic"
    assert base64.b64decode(encoded).decode() == f"alerts:{secret}"
    assert secret not in repr(credentials)
    assert secret not in repr(AdminSettings())


@pytest.mark.parametrize(
    "values",
    [
        {"notify_username": "alerts"},
        {"notify_password": "x" * 12},
        {"notify_token": "tk_x", "notify_username": "alerts", "notify_password": "x" * 12},
        {"notify_username": "a:b", "notify_password": "x" * 12},
        {"notify_token": "tk_a b"},
        {"notify_token": "tk_ñ"},
        {"notify_token": "tk_a\nInjected: yes"},
        {"notify_password": "x\r\n", "notify_username": "alerts"},
        {"notify_token": "x" * 513},
    ],
)
def test_invalid_credentials_are_refused_without_echoing_them(
    values: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("token", "username", "password"):
        monkeypatch.delenv(f"UT_NOTIFY_{name.upper()}", raising=False)
    for key, value in values.items():
        monkeypatch.setenv(f"UT_{key.upper()}", value)
    with pytest.raises(ValidationError) as caught:
        AdminSettings()
    for value in values.values():
        if len(value) > 3:  # short fragments may occur in the message itself
            assert value not in str(caught.value)
            assert repr(value)[1:-1] not in str(caught.value)


# ---------------------------------------------------------------------- the request


def test_bearer_token_goes_to_ntfy_and_webhook() -> None:
    token = ntfy_token()
    transport = RecordingTransport()
    sender = Sender(transport, public_dns, Credentials.bearer(token, HOST))
    assert sender.auth_kind == "token"
    assert _deliver(sender, Target("ntfy", NTFY)) == "sent"
    assert _deliver(sender, Target("webhook", NTFY)) == "sent"
    for request in transport.requests:
        assert request.headers["authorization"] == f"Bearer {token}"
        assert request.url.host == "ntfy.example.com"
        assert request.url.scheme == "https"


def test_basic_credentials() -> None:
    secret = password()
    transport = RecordingTransport()
    sender = Sender(transport, public_dns, Credentials.basic("alerts", secret, HOST))
    assert sender.auth_kind == "basic"
    assert _deliver(sender, Target("ntfy", NTFY)) == "sent"
    header = transport.requests[-1].headers["authorization"]
    assert header == "Basic " + base64.b64encode(f"alerts:{secret}".encode()).decode()


def test_no_header_without_credentials() -> None:
    transport = RecordingTransport()
    sender = Sender(transport, public_dns)
    assert sender.auth_kind is None
    assert _deliver(sender, Target("ntfy", NTFY)) == "sent"
    assert "authorization" not in transport.requests[-1].headers


class Redirecting(httpx.AsyncBaseTransport):
    """Answers every request with a redirect to another host, and records them."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(307, headers={"location": "https://elsewhere.example.org/x"})


def test_credentials_never_follow_a_redirect() -> None:
    transport = Redirecting()
    sender = Sender(transport, public_dns, Credentials.bearer(ntfy_token(), HOST))
    assert _deliver(sender, Target("ntfy", NTFY)) == "failed"
    assert [r.url.host for r in transport.requests] == ["ntfy.example.com"]


def test_no_header_when_the_send_is_refused_before_connecting() -> None:
    transport = RecordingTransport()

    async def loopback(host: str) -> list[str]:
        return ["127.0.0.1"]

    sender = Sender(transport, loopback, Credentials.bearer(ntfy_token(), HOST))
    assert _deliver(sender, Target("ntfy", NTFY)) == "failed"
    assert transport.requests == []


@pytest.mark.parametrize("status", [401, 403])
def test_rejected_credentials_are_reported_and_never_logged(
    status: int, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    token = ntfy_token()
    with_token = Sender(RecordingTransport(status), public_dns, Credentials.bearer(token, HOST))
    assert _deliver(with_token, Target("ntfy", NTFY)) == "rejected"
    assert "credentials rejected" in caplog.text
    without = Sender(RecordingTransport(status), public_dns)
    assert _deliver(without, Target("ntfy", NTFY)) == "rejected"
    assert asyncio.run(without.send(Target("ntfy", NTFY), MESSAGE)) is False
    assert "it needs credentials" in caplog.text
    # Even with httpx at DEBUG (production keeps it at WARNING, `logging.QUIET_LOGGERS`).
    assert token not in caplog.text
    ours = [r.getMessage() for r in caplog.records if r.name.startswith("ultimatetunes")]
    assert ours
    assert not any("ut-alerts" in line for line in ours)


def test_install_reads_the_credentials_from_the_settings(services: Services) -> None:
    app = FastAPI()
    web.install(app, services, _settings(notify_token=ntfy_token()))
    assert app.state.admin.sender.auth_kind == "token"
    plain = FastAPI()
    web.install(plain, services, _settings())
    assert plain.state.admin.sender.auth_kind is None


# ---------------------------------------------------------------------- the panel


def _use_sender(client: TestClient, sender: Sender) -> None:
    client.app.state.admin.sender = sender  # type: ignore[attr-defined]


def test_page_says_whether_credentials_are_set_but_never_shows_them(
    client: TestClient, admin_csrf: str, transport: RecordingTransport
) -> None:
    page = client.get("/admin/notifications").text
    assert "Credentials: not set" in page
    assert "UT_NOTIFY_TOKEN" in page
    token, secret = ntfy_token(), password()
    _use_sender(client, Sender(transport, public_dns, Credentials.bearer(token, HOST)))
    page = client.get("/admin/notifications").text
    assert "Access token: set ✓" in page
    assert token not in page
    assert "Bearer" not in page
    _use_sender(client, Sender(transport, public_dns, Credentials.basic("alerts", secret, HOST)))
    page = client.get("/admin/notifications", headers={"accept-language": "es"}).text
    assert "Usuario y contraseña: configurados ✓" in page
    assert secret not in page
    # The panel has no field that takes them.
    assert 'name="token"' not in page
    assert 'name="password"' not in page


def test_test_button_reports_rejected_credentials(
    client: TestClient, admin_csrf: str, transport: RecordingTransport
) -> None:
    token = ntfy_token()
    _use_sender(client, Sender(transport, public_dns, Credentials.bearer(token, HOST)))
    client.post("/admin/notifications", data={"csrf": admin_csrf, "kind": "ntfy", "url": NTFY})
    sent = client.post("/admin/notifications/test", data={"csrf": admin_csrf})
    assert sent.headers["location"].endswith("done=notify_sent")
    assert transport.requests[-1].headers["authorization"] == f"Bearer {token}"
    transport.status = 401
    rejected = client.post("/admin/notifications/test", data={"csrf": admin_csrf})
    assert rejected.headers["location"] == "/admin/notifications?done=notify_rejected"
    shown = client.get(rejected.headers["location"]).text
    assert "ntfy rejected the credentials" in shown
    client.post("/admin/notifications", data={"csrf": admin_csrf, "kind": "webhook", "url": NTFY})
    transport.status = 403
    hook = client.post("/admin/notifications/test", data={"csrf": admin_csrf})
    assert hook.headers["location"].endswith("done=notify_rejected_webhook")
    audit = client.get("/admin/audit").text
    assert "notify.test" in audit
    assert "rejected" in audit
    assert "token" in audit
    assert token not in audit


def test_test_button_needs_admin_and_csrf(client: TestClient, admin_csrf: str) -> None:
    assert client.post("/admin/notifications/test", data={"csrf": "nope"}).status_code == 403


# ---------------------------------------------------------------------- the bound host


def test_credentials_need_the_bound_host(monkeypatch: pytest.MonkeyPatch) -> None:
    token = ntfy_token()
    monkeypatch.delenv("UT_NOTIFY_HOST")
    monkeypatch.setenv("UT_NOTIFY_TOKEN", token)
    with pytest.raises(ValidationError) as caught:
        AdminSettings()
    assert "UT_NOTIFY_HOST is required" in str(caught.value)
    assert token not in str(caught.value)
    # A host alone (no credentials) is harmless; blank means unset.
    monkeypatch.delenv("UT_NOTIFY_TOKEN")
    monkeypatch.setenv("UT_NOTIFY_HOST", " ")
    assert AdminSettings().notify_host is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ntfy.example.com", ("ntfy.example.com", 443)),
        (" NTFY.Example.com.:8443 ", ("ntfy.example.com", 8443)),
        ("[fd00::1]:8443", ("fd00::1", 8443)),
        ("192.168.1.30", ("192.168.1.30", 443)),
    ],
)
def test_host_and_port(text: str, expected: tuple[str, int]) -> None:
    assert host_and_port(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "https://ntfy.example.com",
        "ntfy.example.com/x",
        "u@ntfy.example.com",
        ":443",
        "ntfy.example.com:99999",
        "ntfy.example.com:abc",
        "a b",
        "ntfy\x01",
    ],
)
def test_bad_hosts_are_refused(text: str, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="UT_NOTIFY_HOST"):
        host_and_port(text)
    if text.strip():
        monkeypatch.setenv("UT_NOTIFY_HOST", text)
        with pytest.raises(ValidationError):
            AdminSettings()


def test_where_and_applies_to() -> None:
    plain = Credentials.bearer(ntfy_token(), HOST)
    assert plain.where == HOST
    assert plain.applies_to(f"https://{HOST}/t")
    assert plain.applies_to("https://NTFY.example.com.:443/t")
    assert not plain.applies_to(f"https://{HOST}:8443/t")
    assert not plain.applies_to(f"https://{HOST}:99999/t")
    assert not plain.applies_to(f"http://{HOST}/t")
    assert not plain.applies_to("https://ntfy.example.com.evil.example/t")
    assert not plain.applies_to(f"https://evil.example/{HOST}")
    ported = Credentials.basic("alerts", password(), "[fd00::1]:8443")
    assert ported.where == "[fd00::1]:8443"
    assert ported.applies_to("https://[fd00::1]:8443/t")
    assert not ported.applies_to("https://[fd00::1]/t")


@pytest.mark.parametrize("kind", ["ntfy", "webhook"])
@pytest.mark.parametrize(
    "url", ["https://other.example.org/ut-alerts", f"https://{HOST}:8443/ut-alerts"]
)
def test_another_host_gets_no_credentials(
    kind: str, url: str, caplog: pytest.LogCaptureFixture
) -> None:
    """An admin who points the URL elsewhere never sends the credentials there."""
    token = ntfy_token()
    transport = RecordingTransport()
    sender = Sender(transport, public_dns, Credentials.bearer(token, HOST))
    target = Target(kind, url)  # type: ignore[arg-type]
    assert not sender.credentials_apply(target)
    assert _deliver(sender, target) == "sent"
    assert "authorization" not in transport.requests[-1].headers
    assert "without credentials" in caplog.text
    assert token not in caplog.text
    assert _deliver(sender, Target(kind, NTFY)) == "sent"  # type: ignore[arg-type]
    assert transport.requests[-1].headers["authorization"] == f"Bearer {token}"


def test_page_warns_when_the_url_is_not_on_the_bound_host(
    client: TestClient, admin_csrf: str, transport: RecordingTransport
) -> None:
    token = ntfy_token()
    _use_sender(client, Sender(transport, public_dns, Credentials.bearer(token, HOST)))
    client.post("/admin/notifications", data={"csrf": admin_csrf, "kind": "ntfy", "url": NTFY})
    page = client.get("/admin/notifications").text
    assert f"sent only to {HOST}" in page
    assert "without credentials" not in page
    other = "https://other.example.org/ut-alerts"
    client.post("/admin/notifications", data={"csrf": admin_csrf, "kind": "ntfy", "url": other})
    page = client.get("/admin/notifications").text
    assert "is not on UT_NOTIFY_HOST" in page
    assert token not in page
    client.post("/admin/notifications/test", data={"csrf": admin_csrf})
    assert "authorization" not in transport.requests[-1].headers
    audit = client.get("/admin/audit").text
    assert "other.example.org" in audit
    assert token not in audit
