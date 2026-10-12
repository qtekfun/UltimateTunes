# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Passwords, users, keys and the audit log of `AuthService` (RF-01; admin panel T15)."""

import json
import secrets

import pytest
from argon2 import PasswordHasher, Type

from tests.auth.conftest import ADMIN_PASSWORD, IP, USER_PASSWORD, Account, fast_passwords
from ultimatetunes.auth import keys
from ultimatetunes.auth.passwords import Passwords
from ultimatetunes.auth.service import AuthService, check_key_name, check_username
from ultimatetunes.auth.settings import AuthSettings
from ultimatetunes.core.authn import Principal
from ultimatetunes.core.clock import FakeClock, format_ts
from ultimatetunes.core.ratelimit import SqliteRateLimiter
from ultimatetunes.db import Database
from ultimatetunes.errors import (
    AccountDisabled,
    AuthenticationFailed,
    Conflict,
    ConflictingAuth,
    Forbidden,
    InvalidApiKey,
    InvalidParameter,
    NotFound,
    RateLimited,
)

OTHER_IP = "198.51.100.7"
# Callers on the Internet and on the LAN, and a wrong guess (random, never a real secret).
STRANGERS = tuple(f"203.0.113.{n}" for n in range(1, 5))
NEIGHBOURS = tuple(f"192.168.1.{n}" for n in range(10, 13))
WRONG = secrets.token_hex(8)


def actions(service: AuthService) -> list[str]:
    return [e.action for e in reversed(service.recent_audit())]


# ---------------------------------------------------------------- passwords


def test_verify_password(service: AuthService, admin: Account, clock: FakeClock) -> None:
    user = service.verify_password(" ALICE ", ADMIN_PASSWORD, IP)
    assert user.id == admin.user_id
    assert service.get_user(admin.user_id).last_login_at == format_ts(clock.now())


def test_wrong_password_and_unknown_user_look_the_same(
    service: AuthService, admin: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    burned: list[str] = []
    monkeypatch.setattr(Passwords, "burn", lambda self, password: burned.append("x"))
    with pytest.raises(AuthenticationFailed) as wrong:
        service.verify_password("alice", "not the password", IP)
    with pytest.raises(AuthenticationFailed) as unknown:
        service.verify_password("nobody", "not the password", OTHER_IP)
    assert wrong.value.message == unknown.value.message
    assert burned == ["x"]


def test_disabled_user_with_the_right_password(service: AuthService, user: Account) -> None:
    service.set_disabled(user.user_id, True, actor=None)
    with pytest.raises(AuthenticationFailed):
        service.verify_password("bob", "wrong password!", IP)
    with pytest.raises(AccountDisabled):
        service.verify_password("bob", USER_PASSWORD, IP)


def test_password_failures_lock_the_username_across_ips(
    service: AuthService, admin: Account, clock: FakeClock
) -> None:
    with pytest.raises(AuthenticationFailed):
        service.verify_password("alice", "guess one", "203.0.113.1")
    with pytest.raises(AuthenticationFailed):
        service.verify_password("alice", "guess two", "203.0.113.2")
    # Locked for 60 s: even the right password is refused, before Argon2 runs.
    with pytest.raises(RateLimited) as caught:
        service.verify_password("alice", ADMIN_PASSWORD, "203.0.113.3")
    assert caught.value.retry_after_s == 60
    lockout = [e for e in service.recent_audit() if e.action == "auth.lockout"]
    assert [(e.target_type, e.target_id) for e in lockout] == [("user-out", "alice")]
    clock.advance(60)
    assert service.verify_password("alice", ADMIN_PASSWORD, IP).id == admin.user_id


def test_strangers_cannot_lock_out_logins_from_trusted_networks(
    service: AuthService, admin: Account
) -> None:
    """Audit M1: wrong passwords from the Internet (`POST /ut/v1/keys`) lock only the outside
    counter; the admin still logs in from LAN/Tailscale."""
    for stranger in STRANGERS[:2]:
        with pytest.raises(AuthenticationFailed):
            service.create_key_with_password("alice", WRONG, "Laptop", stranger)
    with pytest.raises(RateLimited):
        service.verify_password("alice", ADMIN_PASSWORD, STRANGERS[2])
    inside = service.verify_password("alice", ADMIN_PASSWORD, IP, trusted=True)
    assert inside.id == admin.user_id
    created = service.create_key_with_password("alice", ADMIN_PASSWORD, "Phone", IP, trusted=True)
    assert created.key.user_id == admin.user_id
    # The outside counter is still locked: a success inside does not reset it.
    with pytest.raises(RateLimited):
        service.verify_password("alice", ADMIN_PASSWORD, STRANGERS[3])


def test_failures_from_trusted_networks_lock_only_the_inside_counter(
    service: AuthService, admin: Account
) -> None:
    for neighbour in NEIGHBOURS[:2]:
        with pytest.raises(AuthenticationFailed):
            service.verify_password("alice", WRONG, neighbour, trusted=True)
    with pytest.raises(RateLimited):
        service.verify_password("alice", ADMIN_PASSWORD, NEIGHBOURS[2], trusted=True)
    lockout = [e for e in service.recent_audit() if e.action == "auth.lockout"]
    assert [(e.target_type, e.target_id) for e in lockout] == [("user", "alice")]
    assert service.verify_password("alice", ADMIN_PASSWORD, OTHER_IP).id == admin.user_id


def test_password_failures_lock_the_ip(service: AuthService, admin: Account) -> None:
    for name in ("x1", "x2", "x3"):
        with pytest.raises(AuthenticationFailed):
            service.verify_password(name, "guess", IP)
    with pytest.raises(RateLimited):
        service.verify_password("alice", ADMIN_PASSWORD, IP)
    assert service.verify_password("alice", ADMIN_PASSWORD, OTHER_IP).id == admin.user_id


def test_success_clears_the_failure_count(service: AuthService, admin: Account) -> None:
    for _ in range(3):
        with pytest.raises(AuthenticationFailed):
            service.verify_password("alice", "guess", IP)
        service.verify_password("alice", ADMIN_PASSWORD, IP)
    service.verify_password("alice", ADMIN_PASSWORD, IP)


def test_login_rate_limit(db: Database, clock: FakeClock, auth_settings: AuthSettings) -> None:
    tight = auth_settings.model_copy(update={"auth_login_burst": 2.0})
    service = AuthService(db, clock, SqliteRateLimiter(db, clock), tight, fast_passwords())
    service.create_user("alice", ADMIN_PASSWORD, "admin", actor=None)
    service.verify_password("alice", ADMIN_PASSWORD, IP)
    service.verify_password("alice", ADMIN_PASSWORD, IP)
    with pytest.raises(RateLimited):
        service.verify_password("alice", ADMIN_PASSWORD, IP)
    assert service.verify_password("alice", ADMIN_PASSWORD, OTHER_IP).username == "alice"


@pytest.mark.parametrize("client_ip", [None, ""])
def test_password_checks_need_the_client_address(
    service: AuthService, admin: Account, client_ip: str | None
) -> None:
    with pytest.raises(Forbidden):
        service.verify_password("alice", ADMIN_PASSWORD, client_ip)
    with pytest.raises(Forbidden):
        service.create_key_with_password("alice", ADMIN_PASSWORD, "Laptop", client_ip)


def test_repr_never_shows_secrets(service: AuthService, admin: Account) -> None:
    user = service.get_user(admin.user_id)
    assert user.password_hash not in repr(user)
    assert user.password_hash not in str(user)
    assert "password_hash" not in repr(user)
    created = service.create_key(admin.user_id, "Laptop", actor=None)
    for text in (repr(created), str(created), repr(created.key)):
        assert created.secret not in text
    assert "secret" not in repr(created)


def test_password_is_rehashed_when_parameters_change(
    db: Database, clock: FakeClock, service: AuthService, admin: Account
) -> None:
    before = service.get_user(admin.user_id).password_hash
    stronger = Passwords(PasswordHasher(time_cost=2, memory_cost=16, parallelism=1, type=Type.ID))
    upgraded = AuthService(db, clock, SqliteRateLimiter(db, clock), passwords=stronger)
    upgraded.verify_password("alice", ADMIN_PASSWORD, IP)
    after = service.get_user(admin.user_id).password_hash
    assert after != before
    assert "t=2" in after
    upgraded.verify_password("alice", ADMIN_PASSWORD, IP)
    assert service.get_user(admin.user_id).password_hash == after


# ---------------------------------------------------------------- users


def test_create_user(service: AuthService, clock: FakeClock) -> None:
    user = service.create_user("Carol.M", "a long password here", "user", actor=None)
    assert user.username == "carol.m"
    assert user.role == "user"
    assert not user.is_disabled
    assert user.created_at == user.updated_at == format_ts(clock.now())
    assert user.password_hash.startswith("$argon2id$")
    assert service.get_user(user.id) == user
    assert [u.username for u in service.list_users()] == ["carol.m"]
    with pytest.raises(Conflict):
        service.create_user("CAROL.m", "a long password here", "user", actor=None)
    (entry,) = service.recent_audit()
    assert entry.action == "user.create"
    assert entry.target_id == user.id
    assert json.loads(entry.detail or "") == {"role": "user", "username": "carol.m"}


@pytest.mark.parametrize("username", ["", " ", "-x", "a b", "a/b", "x" * 65, "é"])
def test_invalid_usernames(service: AuthService, username: str) -> None:
    with pytest.raises(InvalidParameter):
        check_username(username)
    with pytest.raises(InvalidParameter):
        service.create_user(username, "a long password here", "user", actor=None)


def test_valid_usernames() -> None:
    assert check_username("a") == "a"
    assert check_username("x" * 64) == "x" * 64
    assert check_username(" Ana_B-2.c ") == "ana_b-2.c"


def test_create_user_checks_password_and_role(service: AuthService) -> None:
    with pytest.raises(InvalidParameter):
        service.create_user("dave", "short", "user", actor=None)
    with pytest.raises(InvalidParameter):
        service.create_user("dave", "a long password here", "root", actor=None)
    assert service.list_users() == []


def test_bootstrap_admin_only_once(service: AuthService) -> None:
    assert service.bootstrap_admin("Root", "the first admin password", IP)
    (admin,) = service.list_users()
    assert (admin.username, admin.role) == ("root", "admin")
    assert not service.bootstrap_admin("other", "another admin password")
    assert not service.bootstrap_admin("root", "a password to reset it")
    assert service.verify_password("root", "the first admin password", IP).id == admin.id
    with pytest.raises(InvalidParameter):
        service.bootstrap_admin("x", "short")


def test_user_changes_are_audited(
    service: AuthService, admin: Account, user: Account, clock: FakeClock
) -> None:
    actor = Principal(admin.user_id, admin.username, "admin")
    clock.advance(1)
    service.set_role(user.user_id, "admin", actor=actor, client_ip=IP)
    assert service.get_user(user.user_id).role == "admin"
    clock.advance(1)
    service.set_password(user.user_id, "a brand new password", actor=actor, client_ip=IP)
    assert service.verify_password("bob", "a brand new password", IP).id == user.user_id
    clock.advance(1)
    service.set_disabled(user.user_id, True, actor=actor)
    assert service.get_user(user.user_id).is_disabled
    clock.advance(1)
    service.set_disabled(user.user_id, False, actor=actor)
    assert actions(service)[-4:] == ["user.role", "user.password", "user.disable", "user.enable"]
    latest = service.recent_audit()[0]
    assert (latest.actor_user_id, latest.target_type, latest.target_id) == (
        admin.user_id,
        "user",
        user.user_id,
    )
    with pytest.raises(InvalidParameter):
        service.set_role(user.user_id, "owner", actor=actor)
    with pytest.raises(InvalidParameter):
        service.set_password(user.user_id, "short", actor=actor)


def test_unknown_user(service: AuthService) -> None:
    missing = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01dfff"
    with pytest.raises(NotFound):
        service.get_user(missing)
    with pytest.raises(NotFound):
        service.set_disabled(missing, True, actor=None)
    with pytest.raises(NotFound):
        service.set_role(missing, "user", actor=None)
    with pytest.raises(NotFound):
        service.set_password(missing, "a long password here", actor=None)
    with pytest.raises(NotFound):
        service.create_key(missing, "Phone", actor=None)
    assert service.recent_audit() == []


# ---------------------------------------------------------------- keys


def test_create_key_stores_only_hash_and_prefix(
    service: AuthService, db: Database, admin: Account, clock: FakeClock
) -> None:
    created = service.create_key(admin.user_id, "  Pixel 9 ", actor=None)
    assert keys.is_well_formed(created.secret)
    assert created.key.name == "Pixel 9"
    assert created.key.prefix == created.secret[:12]
    assert created.key.created_at == format_ts(clock.now())
    assert (created.key.last_used_at, created.key.revoked_at) == (None, None)
    with db.read() as conn:
        dump = json.dumps([dict(r) for r in conn.execute("SELECT * FROM api_keys").fetchall()])
        audit = json.dumps([dict(r) for r in conn.execute("SELECT * FROM audit_log").fetchall()])
    assert created.secret not in dump
    assert created.secret not in audit
    assert keys.digest(created.secret) in dump


@pytest.mark.parametrize("name", ["", "   ", "x" * 101, "tab\there", "new\nline"])
def test_key_names(service: AuthService, admin: Account, name: str) -> None:
    with pytest.raises(InvalidParameter):
        check_key_name(name)
    with pytest.raises(InvalidParameter):
        service.create_key(admin.user_id, name, actor=None)


def test_hash_collision_is_refused(
    service: AuthService, admin: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(keys, "generate", lambda: admin.key)
    with pytest.raises(Conflict):
        service.create_key(admin.user_id, "Twin", actor=None)


def test_list_keys_newest_first_with_revoked(
    service: AuthService, admin: Account, user: Account, clock: FakeClock
) -> None:
    clock.advance(1)
    newer = service.create_key(admin.user_id, "Tablet", actor=None)
    clock.advance(1)
    service.revoke_key(admin.key_id, actor=None)
    listed = service.list_keys(admin.user_id)
    assert [k.id for k in listed] == [newer.key.id, admin.key_id]
    assert listed[1].revoked_at == format_ts(clock.now())
    assert [k.id for k in service.list_keys(user.user_id)] == [user.key_id]


def test_revoke_own_key(service: AuthService, admin: Account, user: Account) -> None:
    me = service.authenticate_api_key(admin.key, None, IP)
    with pytest.raises(NotFound):
        service.revoke_own_key(me, user.key_id, IP)
    with pytest.raises(NotFound):
        service.revoke_own_key(me, "0199d6a2-4c1e-7b3a-9f10-2a6c8e01ffff", IP)
    service.revoke_own_key(me, admin.key_id, IP)
    service.revoke_own_key(me, admin.key_id, IP)  # idempotent
    with pytest.raises(InvalidApiKey):
        service.authenticate_api_key(admin.key, None, IP)
    assert actions(service).count("key.revoke") == 1
    entry = next(e for e in service.recent_audit() if e.action == "key.revoke")
    assert (entry.actor_user_id, entry.actor_ip, entry.target_id) == (
        admin.user_id,
        IP,
        admin.key_id,
    )
    # The user's key is untouched.
    service.authenticate_api_key(user.key, None, IP)


def test_admin_revokes_any_key(service: AuthService, admin: Account, user: Account) -> None:
    service.revoke_key(user.key_id, actor=Principal(admin.user_id, "alice", "admin"))
    with pytest.raises(InvalidApiKey):
        service.authenticate_api_key(user.key, None, IP)
    with pytest.raises(NotFound):
        service.revoke_key("0199d6a2-4c1e-7b3a-9f10-2a6c8e01ffff", actor=None)


def test_create_key_with_password(service: AuthService, admin: Account, clock: FakeClock) -> None:
    clock.advance(1)
    created = service.create_key_with_password("Alice", ADMIN_PASSWORD, "Laptop", IP)
    principal = service.authenticate_api_key(created.secret, None, IP)
    assert principal.user_id == admin.user_id
    assert principal.api_key_id == created.key.id
    entry = service.recent_audit()[0]
    assert (entry.action, entry.actor_user_id, entry.actor_ip) == ("key.create", admin.user_id, IP)
    assert json.loads(entry.detail or "") == {"name": "Laptop"}


def test_create_key_with_password_failures(
    service: AuthService, admin: Account, user: Account
) -> None:
    with pytest.raises(AuthenticationFailed):
        service.create_key_with_password("alice", "wrong password", "Laptop", IP)
    with pytest.raises(InvalidParameter):
        service.create_key_with_password("alice", ADMIN_PASSWORD, " ", IP)
    # A key sent along must be valid and of the same user.
    same = service.create_key_with_password("alice", ADMIN_PASSWORD, "Laptop", IP, admin.key)
    assert same.key.user_id == admin.user_id
    with pytest.raises(ConflictingAuth):
        service.create_key_with_password("alice", ADMIN_PASSWORD, "Laptop", IP, user.key)
    with pytest.raises(InvalidApiKey):
        service.create_key_with_password("alice", ADMIN_PASSWORD, "Laptop", OTHER_IP, "utk_x")
    assert len(service.list_keys(admin.user_id)) == 2
