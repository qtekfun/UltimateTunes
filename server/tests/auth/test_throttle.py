# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Brute-force brakes: IPv6 /64 grouping, Argon2 slots and the global failure budget."""

import threading

import pytest

from tests.auth.conftest import ADMIN_PASSWORD, IP, Account, fast_passwords
from ultimatetunes.auth import throttle
from ultimatetunes.auth.service import AuthService
from ultimatetunes.auth.settings import AuthSettings
from ultimatetunes.auth.throttle import Argon2Slots, client_key, shared_slots
from ultimatetunes.core.clock import FakeClock
from ultimatetunes.core.ratelimit import SqliteRateLimiter
from ultimatetunes.db import Database
from ultimatetunes.errors import AuthenticationFailed, InvalidApiKey, RateLimited

UNKNOWN_KEY = "utk_EXAMPLEexampleEXAMPLEexampleEXAMPLEexampleE"


@pytest.mark.parametrize(
    ("client_ip", "key"),
    [
        ("192.0.2.10", "192.0.2.10"),
        ("::ffff:192.0.2.10", "192.0.2.10"),
        ("2001:db8:1:2:aaaa:bbbb:cccc:dddd", "2001:db8:1:2::/64"),
        ("2001:db8:1:2::1", "2001:db8:1:2::/64"),
        ("fe80::1%eth0", "fe80::/64"),
        ("not-an-ip", "not-an-ip"),
        (None, "unknown"),
        ("", "unknown"),
    ],
)
def test_client_keys(client_ip: str | None, key: str) -> None:
    assert client_key(client_ip) == key


def test_one_ipv6_block_shares_one_lockout(service: AuthService, admin: Account) -> None:
    # Three failures (the per-IP limit) from three addresses of one /64 lock the whole block.
    for host in ("1", "2", "3"):
        with pytest.raises(InvalidApiKey):
            service.authenticate_api_key(UNKNOWN_KEY, None, f"2001:db8:1:2::{host}")
    with pytest.raises(RateLimited):
        service.authenticate_api_key(UNKNOWN_KEY, None, "2001:db8:1:2:ffff::9")
    with pytest.raises(RateLimited):
        service.verify_password("alice", ADMIN_PASSWORD, "2001:db8:1:2::77")
    # The next /64 is somebody else.
    with pytest.raises(InvalidApiKey):
        service.authenticate_api_key(UNKNOWN_KEY, None, "2001:db8:1:3::1")
    assert service.verify_password("alice", ADMIN_PASSWORD, "2001:db8:1:3::1").username == "alice"
    (entry,) = [e for e in service.recent_audit() if e.action == "auth.lockout"]
    assert entry.target_id == "2001:db8:1:2::/64"


def test_the_login_rate_limit_groups_ipv6_too(
    db: Database, clock: FakeClock, auth_settings: AuthSettings
) -> None:
    tight = auth_settings.model_copy(update={"auth_login_burst": 1.0})
    service = AuthService(db, clock, SqliteRateLimiter(db, clock), tight, fast_passwords())
    service.create_user("alice", ADMIN_PASSWORD, "admin", actor=None)
    service.verify_password("alice", ADMIN_PASSWORD, "2001:db8::1")
    with pytest.raises(RateLimited):
        service.verify_password("alice", ADMIN_PASSWORD, "2001:db8::2")


# ---------------------------------------------------------------- Argon2 slots


def test_a_slot_is_held_while_argon2_runs_and_released_after() -> None:
    slots = Argon2Slots(1, wait_s=0)
    with slots.slot():
        with pytest.raises(RateLimited) as busy, slots.slot():
            pass
        assert busy.value.retry_after_s == 1
    with slots.slot():
        pass
    # A failure inside the block still gives the slot back.
    with pytest.raises(ValueError, match="boom"), slots.slot():
        raise ValueError("boom")
    with slots.slot():
        pass


def test_a_check_waits_briefly_for_a_slot() -> None:
    slots = Argon2Slots(1, wait_s=5)
    held = threading.Event()
    release = threading.Event()

    def holder() -> None:
        with slots.slot():
            held.set()
            release.wait(5)

    thread = threading.Thread(target=holder)
    thread.start()
    held.wait(5)
    release.set()
    with slots.slot():  # waits for the holder instead of failing
        pass
    thread.join(5)


@pytest.mark.parametrize(("count", "wait"), [(0, 1.0), (1, -1.0)])
def test_slots_need_sane_settings(count: int, wait: float) -> None:
    with pytest.raises(ValueError, match="slots"):
        Argon2Slots(count, wait)


def test_busy_slots_refuse_password_checks_before_argon2(
    db: Database, clock: FakeClock, auth_settings: AuthSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    slots = Argon2Slots(1, wait_s=0)
    service = AuthService(
        db, clock, SqliteRateLimiter(db, clock), auth_settings, fast_passwords(), slots=slots
    )
    service.create_user("alice", ADMIN_PASSWORD, "admin", actor=None)
    with slots.slot():
        with pytest.raises(RateLimited):
            service.verify_password("alice", ADMIN_PASSWORD, IP)
        with pytest.raises(RateLimited):
            service.verify_password("nobody", ADMIN_PASSWORD, IP)
    assert service.verify_password("alice", ADMIN_PASSWORD, IP).username == "alice"
    # A busy server is not a failed guess: nothing was counted against the IP or the user.
    with pytest.raises(AuthenticationFailed):
        service.verify_password("alice", "wrong one", IP)
    assert service.verify_password("alice", ADMIN_PASSWORD, IP).username == "alice"


def test_every_service_shares_one_set_of_slots(
    monkeypatch: pytest.MonkeyPatch, db: Database, clock: FakeClock
) -> None:
    shared_slots.cache_clear()
    monkeypatch.setenv("UT_AUTH_ARGON2_CONCURRENCY", "3")
    try:
        first = shared_slots()
        assert shared_slots() is first
        service = AuthService(db, clock, SqliteRateLimiter(db, clock))
        assert service._slots is first
        assert AuthSettings().auth_argon2_concurrency == 3
    finally:
        shared_slots.cache_clear()
    assert throttle.IPV6_GROUP == 64


# ---------------------------------------------------------------- global failure budget


@pytest.fixture
def budgeted(db: Database, clock: FakeClock, auth_settings: AuthSettings) -> AuthService:
    settings = auth_settings.model_copy(
        update={"auth_max_failures_global_per_min": 4, "auth_global_lockout_s": 30}
    )
    service = AuthService(db, clock, SqliteRateLimiter(db, clock), settings, fast_passwords())
    service.create_user("alice", ADMIN_PASSWORD, "admin", actor=None)
    return service


def test_too_many_failures_from_anywhere_lock_everyone(
    budgeted: AuthService, clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    alice = budgeted.create_key(
        budgeted.verify_password("alice", ADMIN_PASSWORD, IP).id, "phone", actor=None
    )
    # Four failures from four addresses: within budget; the fifth goes over it.
    for n in range(1, 6):
        with pytest.raises(InvalidApiKey):
            budgeted.authenticate_api_key(UNKNOWN_KEY, None, f"198.51.100.{n}")
    with pytest.raises(RateLimited) as locked:
        budgeted.authenticate_api_key(UNKNOWN_KEY, None, "203.0.113.50")
    assert locked.value.retry_after_s == 30
    with pytest.raises(RateLimited):
        budgeted.verify_password("alice", ADMIN_PASSWORD, "203.0.113.51")
    # A valid key is never refused for it.
    assert budgeted.authenticate_api_key(alice.secret, None, "203.0.113.52").username == "alice"
    assert "auth lockout of everyone for 30 s" in caplog.text
    entries = [e for e in budgeted.recent_audit() if e.action == "auth.lockout"]
    assert [(e.target_type, e.target_id) for e in entries] == [("global", None)]
    clock.advance(30)
    assert budgeted.verify_password("alice", ADMIN_PASSWORD, "203.0.113.51").username == "alice"


def test_the_failure_budget_refills_over_time(budgeted: AuthService, clock: FakeClock) -> None:
    for minute in range(3):
        for n in range(4):
            with pytest.raises(InvalidApiKey):
                budgeted.authenticate_api_key(UNKNOWN_KEY, None, f"198.51.{minute}.{n}")
        clock.advance(60)
    assert budgeted.verify_password("alice", ADMIN_PASSWORD, IP).username == "alice"
