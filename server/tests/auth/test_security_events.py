# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Every outcome of `AuthService` is a structured security event with the client address,
and none of them carries a password or a key (docs/logging.md)."""

import secrets

import pytest

from tests.auth.conftest import ADMIN_PASSWORD, IP, Account, fast_passwords
from tests.security_events import Events, rendered
from ultimatetunes.auth.service import AuthService
from ultimatetunes.auth.settings import AuthSettings
from ultimatetunes.auth.throttle import Argon2Slots
from ultimatetunes.core.clock import FakeClock
from ultimatetunes.core.ratelimit import SqliteRateLimiter
from ultimatetunes.db import Database
from ultimatetunes.errors import (
    AccountDisabled,
    AuthenticationFailed,
    AuthenticationRequired,
    ConflictingAuth,
    Forbidden,
    InvalidApiKey,
    RateLimited,
    TokenAuthNotSupported,
)

UNKNOWN_KEY = "utk_EXAMPLEexampleEXAMPLEexampleEXAMPLEexampleE"
OUTSIDE = "203.0.113.40"
WRONG = secrets.token_urlsafe(18)


def params(**values: str) -> dict[str, list[str]]:
    return {name: [value] for name, value in values.items()}


def tuned(db: Database, clock: FakeClock, settings: AuthSettings, **update: object) -> AuthService:
    return AuthService(
        db,
        clock,
        SqliteRateLimiter(db, clock),
        settings.model_copy(update=update),
        fast_passwords(),
    )


def test_password_sign_ins(
    service: AuthService,
    admin: Account,
    clock: FakeClock,
    events: Events,
    caplog: pytest.LogCaptureFixture,
) -> None:
    service.verify_password("Alice", ADMIN_PASSWORD, IP)
    with pytest.raises(AuthenticationFailed):
        service.verify_password("alice", WRONG, OUTSIDE)
    with pytest.raises(AuthenticationFailed):
        service.verify_password("nobody", WRONG, OUTSIDE)
    success = events("auth.success")[-1]
    assert success == {
        "event": "auth.success",
        "client_ip": IP,
        "user": "alice",
        "user_id": admin.user_id,
        "trusted": False,
        "credential": "password",
    }
    known, unknown = events("auth.failure")
    assert known == {
        "event": "auth.failure",
        "reason": "bad_password",
        "client_ip": OUTSIDE,
        "user": "alice",
        "known_user": True,
        "trusted": False,
        "credential": "password",
    }
    assert (unknown["user"], unknown["known_user"]) == ("nobody", False)
    out = rendered(caplog)
    assert WRONG not in out
    assert ADMIN_PASSWORD not in out


def test_the_outside_delay_is_a_throttle_event(
    service: AuthService, admin: Account, events: Events
) -> None:
    with pytest.raises(AuthenticationFailed):
        service.verify_password("alice", WRONG, OUTSIDE)
    with pytest.raises(RateLimited):
        service.verify_password("alice", ADMIN_PASSWORD, OUTSIDE)
    (throttled,) = events("auth.throttled")
    assert throttled == {
        "event": "auth.throttled",
        "reason": "user_backoff",
        "client_ip": OUTSIDE,
        "user": "alice",
        "retry_after_s": 1,
    }


def test_inside_lockout_of_a_username(service: AuthService, admin: Account, events: Events) -> None:
    for _ in range(2):
        with pytest.raises(AuthenticationFailed):
            service.verify_password("alice", WRONG, IP, trusted=True)
    with pytest.raises(RateLimited):
        service.verify_password("alice", ADMIN_PASSWORD, IP, trusted=True)
    (lockout,) = events("auth.lockout")
    assert lockout == {
        "event": "auth.lockout",
        "client_ip": IP,
        "scope": "user",
        "target": "alice",
        "user": "alice",
        "duration_s": 60,
    }
    assert [e["trusted"] for e in events("auth.failure")] == [True, True]
    (throttled,) = events("auth.throttled")
    assert (throttled["reason"], throttled["user"]) == ("user_locked", "alice")


def test_outside_failures_reaching_the_limit_log_the_delay(
    service: AuthService, admin: Account, clock: FakeClock, events: Events
) -> None:
    for _ in range(2):
        with pytest.raises(AuthenticationFailed):
            service.verify_password("alice", WRONG, OUTSIDE)
        clock.advance(10)
    (lockout,) = events("auth.lockout")
    assert (lockout["scope"], lockout["user"], lockout["duration_s"]) == ("user-out", "alice", 2)


def test_invalid_keys_lock_the_ip(service: AuthService, events: Events) -> None:
    for _ in range(3):
        with pytest.raises(InvalidApiKey):
            service.authenticate_api_key(UNKNOWN_KEY, None, IP)
    with pytest.raises(RateLimited):
        service.authenticate_api_key(UNKNOWN_KEY, None, IP)
    failures = events("auth.failure")
    assert [(e["reason"], e["credential"], e["client_ip"]) for e in failures] == [
        ("invalid_key", "api_key", IP)
    ] * 3
    (lockout,) = events("auth.lockout")
    assert (lockout["scope"], lockout["target"], lockout["duration_s"]) == ("ip", IP, 60)
    assert "user" not in lockout
    (throttled,) = events("auth.throttled")
    assert (throttled["reason"], throttled["retry_after_s"]) == ("ip_locked", 60)
    assert "user" not in throttled


def test_api_key_use_is_logged_once_a_minute(
    service: AuthService, admin: Account, clock: FakeClock, events: Events
) -> None:
    for _ in range(3):
        service.authenticate_api_key(admin.key, None, IP)
    clock.advance(61)
    service.authenticate_api_key(admin.key, None, IP)
    service.authenticate_api_key(admin.key, None, "198.51.100.9")
    uses = [e for e in events("auth.success") if e["credential"] == "api_key"]
    assert [e["client_ip"] for e in uses] == [IP, IP, "198.51.100.9"]
    assert uses[0] == {
        "event": "auth.success",
        "client_ip": IP,
        "user": "alice",
        "user_id": admin.user_id,
        "key_id": admin.key_id,
        "credential": "api_key",
    }


def test_stale_keys(service: AuthService, admin: Account, user: Account, events: Events) -> None:
    service.revoke_key(admin.key_id, actor=None)
    with pytest.raises(InvalidApiKey):
        service.authenticate_api_key(admin.key, None, IP)
    service.set_disabled(user.user_id, True, actor=None)
    with pytest.raises(AccountDisabled):
        service.authenticate_api_key(user.key, None, IP)
    revoked, disabled = events("auth.failure")
    assert (revoked["reason"], revoked["key_id"], revoked["user"]) == (
        "revoked_key",
        admin.key_id,
        "alice",
    )
    assert (disabled["reason"], disabled["user"]) == ("account_disabled", "bob")


def test_the_key_rate_limit(
    db: Database, clock: FakeClock, auth_settings: AuthSettings, events: Events
) -> None:
    service = tuned(db, clock, auth_settings, auth_key_rate_per_s=0.001, auth_key_burst=1.0)
    user = service.create_user("carol", ADMIN_PASSWORD, "user", actor=None)
    key = service.create_key(user.id, "phone", actor=None)
    service.authenticate_api_key(key.secret, None, IP)
    with pytest.raises(RateLimited):
        service.authenticate_api_key(key.secret, None, IP)
    (throttled,) = events("auth.throttled")
    assert (throttled["reason"], throttled["user"], throttled["key_id"]) == (
        "key_rate",
        "carol",
        key.key.id,
    )


def test_opensubsonic_refusals(service: AuthService, admin: Account, events: Events) -> None:
    with pytest.raises(TokenAuthNotSupported):
        service.authenticate_subsonic(params(u="alice", t="x", s="y"), IP)
    with pytest.raises(ConflictingAuth):
        service.authenticate_subsonic(params(apiKey=admin.key, u="alice"), IP)
    with pytest.raises(AuthenticationRequired):
        service.authenticate_subsonic(params(u="alice"), IP)
    with pytest.raises(AuthenticationFailed):
        service.authenticate_subsonic(params(u="Alice", p=WRONG), IP)
    reasons = [(e["reason"], e.get("user"), e.get("credential")) for e in events("auth.failure")]
    assert reasons == [
        ("token_auth", "alice", "subsonic_password"),
        ("conflicting_auth", None, "api_key"),
        ("missing_credentials", "alice", None),
        ("bad_credentials", "alice", "subsonic_password"),
    ]


def test_ut_api_refusals(
    service: AuthService, admin: Account, user: Account, events: Events
) -> None:
    with pytest.raises(ConflictingAuth):
        service.authenticate_api_key(admin.key, user.key, IP)
    with pytest.raises(AuthenticationRequired):
        service.authenticate_api_key(None, None, IP)
    assert [e["reason"] for e in events("auth.failure")] == [
        "conflicting_auth",
        "missing_credentials",
    ]


def test_a_key_of_someone_else_with_a_password(
    service: AuthService, admin: Account, user: Account, events: Events
) -> None:
    with pytest.raises(ConflictingAuth):
        service.create_key_with_password("alice", ADMIN_PASSWORD, "tablet", IP, user.key)
    (conflict,) = events("auth.failure")
    assert (conflict["reason"], conflict["user"]) == ("conflicting_auth", "alice")


def test_login_rate_disabled_account_and_missing_address(
    db: Database, clock: FakeClock, auth_settings: AuthSettings, events: Events
) -> None:
    service = tuned(db, clock, auth_settings, auth_login_burst=1.0, auth_login_rate_per_s=0.001)
    carol = service.create_user("carol", ADMIN_PASSWORD, "user", actor=None)
    service.set_disabled(carol.id, True, actor=None)
    with pytest.raises(AccountDisabled):
        service.verify_password("carol", ADMIN_PASSWORD, IP, trusted=True)
    with pytest.raises(RateLimited):
        service.verify_password("carol", ADMIN_PASSWORD, IP, trusted=True)
    with pytest.raises(Forbidden):
        service.verify_password("carol", ADMIN_PASSWORD, None)
    disabled, no_address = events("auth.failure")
    assert (disabled["reason"], disabled["user"]) == ("account_disabled", "carol")
    assert no_address == {
        "event": "auth.failure",
        "reason": "no_client_address",
        "user": "carol",
        "credential": "password",
    }
    (throttled,) = events("auth.throttled")
    assert (throttled["reason"], throttled["user"]) == ("login_rate", "carol")


def test_the_global_lock(
    db: Database, clock: FakeClock, auth_settings: AuthSettings, events: Events
) -> None:
    service = tuned(
        db, clock, auth_settings, auth_max_failures_global_per_min=2, auth_global_lockout_s=30
    )
    for n in range(1, 4):
        with pytest.raises(InvalidApiKey):
            service.authenticate_api_key(UNKNOWN_KEY, None, f"198.51.100.{n}")
    with pytest.raises(RateLimited):
        service.authenticate_api_key(UNKNOWN_KEY, None, "198.51.100.9")
    (lockout,) = events("auth.lockout")
    assert lockout == {
        "event": "auth.lockout",
        "client_ip": "198.51.100.3",
        "scope": "global",
        "duration_s": 30,
    }
    (throttled,) = events("auth.throttled")
    assert (throttled["reason"], throttled["client_ip"]) == ("global_lock", "198.51.100.9")


def test_busy_argon2_slots(
    db: Database, clock: FakeClock, auth_settings: AuthSettings, events: Events
) -> None:
    slots = Argon2Slots(1, wait_s=0)
    service = AuthService(
        db, clock, SqliteRateLimiter(db, clock), auth_settings, fast_passwords(), slots=slots
    )
    with slots.slot(), pytest.raises(RateLimited):
        service.verify_password("alice", WRONG, IP)
    (throttled,) = events("auth.throttled")
    assert throttled == {"event": "auth.throttled", "reason": "argon2_busy"}


def test_audit_entries_are_mirrored_to_the_log(
    service: AuthService, admin: Account, events: Events, caplog: pytest.LogCaptureFixture
) -> None:
    created = service.create_key(admin.user_id, "laptop", actor=None, client_ip=IP)
    entries = events("audit")
    assert entries[-1] == {
        "event": "audit",
        "action": "key.create",
        "client_ip": IP,
        "target_type": "api_key",
        "target_id": created.key.id,
    }
    service.create_user("dave", ADMIN_PASSWORD, "user", actor=None)
    assert [e["action"] for e in events("audit")] == ["key.create", "user.create"]
    assert created.secret not in rendered(caplog)
