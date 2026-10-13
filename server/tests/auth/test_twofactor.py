# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Enrollment, the login second step, recovery codes and the require-policy (auth/twofactor.py)."""

import logging

import pytest

from tests.auth.conftest import Account
from tests.security_events import collect, rendered
from ultimatetunes.auth import totp
from ultimatetunes.auth.service import AuthService
from ultimatetunes.auth.settings import AuthSettings
from ultimatetunes.auth.twofactor import TwoFactorService
from ultimatetunes.core.clock import Clock, FakeClock
from ultimatetunes.errors import Conflict

IP = "192.0.2.50"


@pytest.fixture
def tf(service: AuthService) -> TwoFactorService:
    return service.two_factor


def _now_code(clock: Clock, secret: str) -> str:
    return totp.code_at(secret, int(clock.now().timestamp()))


def _enable(tf: TwoFactorService, clock: FakeClock, user_id: str, username: str) -> list[str]:
    enrollment = tf.begin_enrollment(user_id, username)
    codes = tf.confirm_enrollment(user_id, _now_code(clock, enrollment.secret))
    # Move past the step spent at confirmation so a login code is not refused as a replay.
    clock.advance(totp.PERIOD_S)
    return codes


# ---------------------------------------------------------------------- status and policy


def test_status_of_a_user_without_a_second_factor(tf: TwoFactorService, user: Account) -> None:
    status = tf.status(user.user_id, "user")
    assert not status.enabled
    assert not status.pending
    assert not status.required
    assert status.recovery_remaining == 0
    assert not status.must_enroll


@pytest.mark.parametrize(
    ("policy", "admin_required", "user_required"),
    [("off", False, False), ("admins", True, False), ("all", True, True)],
)
def test_require_policy(
    service: AuthService, policy: str, admin_required: bool, user_required: bool
) -> None:
    tf = AuthService(
        service._db,
        service._clock,
        service._limiter,
        AuthSettings(auth_require_2fa=policy),
        service._passwords,
    ).two_factor
    assert tf.requires("admin") is admin_required
    assert tf.requires("user") is user_required


# ---------------------------------------------------------------------- enrollment


def test_begin_enrollment_stores_a_pending_secret(tf: TwoFactorService, user: Account) -> None:
    enrollment = tf.begin_enrollment(user.user_id, user.username)
    assert enrollment.secret
    assert enrollment.uri.startswith("otpauth://totp/")
    status = tf.status(user.user_id, "user")
    assert status.pending
    assert not status.enabled


def test_confirm_enables_and_returns_recovery_codes(
    tf: TwoFactorService, clock: FakeClock, user: Account
) -> None:
    enrollment = tf.begin_enrollment(user.user_id, user.username)
    codes = tf.confirm_enrollment(user.user_id, _now_code(clock, enrollment.secret))
    assert len(codes) == totp.RECOVERY_CODE_COUNT
    status = tf.status(user.user_id, "user")
    assert status.enabled
    assert not status.pending
    assert status.recovery_remaining == totp.RECOVERY_CODE_COUNT


def test_confirm_with_a_wrong_code_does_not_enable(tf: TwoFactorService, user: Account) -> None:
    tf.begin_enrollment(user.user_id, user.username)
    with pytest.raises(Conflict):
        tf.confirm_enrollment(user.user_id, "000000")
    assert not tf.is_enabled(user.user_id)


def test_confirm_without_starting_is_refused(tf: TwoFactorService, user: Account) -> None:
    with pytest.raises(Conflict):
        tf.confirm_enrollment(user.user_id, "000000")


def test_begin_enrollment_refused_when_already_enabled(
    tf: TwoFactorService, clock: FakeClock, user: Account
) -> None:
    _enable(tf, clock, user.user_id, user.username)
    with pytest.raises(Conflict):
        tf.begin_enrollment(user.user_id, user.username)


def test_restarting_enrollment_replaces_the_pending_secret(
    tf: TwoFactorService, user: Account
) -> None:
    first = tf.begin_enrollment(user.user_id, user.username)
    second = tf.begin_enrollment(user.user_id, user.username)
    assert second.secret != first.secret
    assert tf.status(user.user_id, "user").pending


def test_pending_enrollment_reflects_each_state(
    tf: TwoFactorService, clock: FakeClock, user: Account
) -> None:
    assert tf.pending_enrollment(user.user_id, user.username) is None
    started = tf.begin_enrollment(user.user_id, user.username)
    pending = tf.pending_enrollment(user.user_id, user.username)
    assert pending is not None
    assert pending.secret == started.secret
    tf.confirm_enrollment(user.user_id, _now_code(clock, started.secret))
    assert tf.pending_enrollment(user.user_id, user.username) is None


def test_confirm_when_already_enabled_is_refused(
    tf: TwoFactorService, clock: FakeClock, user: Account
) -> None:
    _enable(tf, clock, user.user_id, user.username)
    with pytest.raises(Conflict):
        tf.confirm_enrollment(user.user_id, "123456")


def test_regenerate_refused_while_only_pending(tf: TwoFactorService, user: Account) -> None:
    tf.begin_enrollment(user.user_id, user.username)
    with pytest.raises(Conflict):
        tf.regenerate_recovery_codes(user.user_id)


def test_verify_fails_closed_while_only_pending(tf: TwoFactorService, user: Account) -> None:
    tf.begin_enrollment(user.user_id, user.username)
    assert not tf.verify_second_factor(user.user_id, "123456", IP)


def test_recovery_code_race_is_treated_as_spent(
    tf: TwoFactorService, clock: FakeClock, user: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ultimatetunes.auth import repository  # noqa: PLC0415

    codes = _enable(tf, clock, user.user_id, user.username)
    # Another request spends the code between the read and the write: mark_used finds no row.
    monkeypatch.setattr(
        repository.RecoveryCodeRepository, "mark_used", lambda self, code_id, now: 0
    )
    assert not tf.verify_second_factor(user.user_id, codes[0], IP)


# ---------------------------------------------------------------------- login second step


def test_verify_accepts_a_current_code(
    tf: TwoFactorService, clock: FakeClock, user: Account
) -> None:
    enrollment = tf.begin_enrollment(user.user_id, user.username)
    secret = enrollment.secret
    tf.confirm_enrollment(user.user_id, _now_code(clock, secret))
    clock.advance(totp.PERIOD_S)
    assert tf.verify_second_factor(user.user_id, _now_code(clock, secret), IP)


def test_a_code_cannot_be_replayed(tf: TwoFactorService, clock: FakeClock, user: Account) -> None:
    enrollment = tf.begin_enrollment(user.user_id, user.username)
    secret = enrollment.secret
    tf.confirm_enrollment(user.user_id, _now_code(clock, secret))
    clock.advance(totp.PERIOD_S)
    code = _now_code(clock, secret)
    assert tf.verify_second_factor(user.user_id, code, IP)
    assert not tf.verify_second_factor(user.user_id, code, IP)


def test_verify_fails_closed_without_enrollment(tf: TwoFactorService, user: Account) -> None:
    assert not tf.verify_second_factor(user.user_id, "123456", IP)


def test_missing_or_empty_code_fails(tf: TwoFactorService, clock: FakeClock, user: Account) -> None:
    _enable(tf, clock, user.user_id, user.username)
    assert not tf.verify_second_factor(user.user_id, "", IP)


def test_recovery_code_works_once(tf: TwoFactorService, clock: FakeClock, user: Account) -> None:
    codes = _enable(tf, clock, user.user_id, user.username)
    assert tf.verify_second_factor(user.user_id, codes[0], IP)
    assert tf.status(user.user_id, "user").recovery_remaining == totp.RECOVERY_CODE_COUNT - 1
    # The same recovery code is spent and never works again.
    assert not tf.verify_second_factor(user.user_id, codes[0], IP)


def test_recovery_code_accepts_lower_case_and_spacing(
    tf: TwoFactorService, clock: FakeClock, user: Account
) -> None:
    codes = _enable(tf, clock, user.user_id, user.username)
    messy = codes[0].lower().replace("-", " ")
    assert tf.verify_second_factor(user.user_id, messy, IP)


def test_second_factor_locks_out_after_repeated_failures(
    tf: TwoFactorService, clock: FakeClock, user: Account
) -> None:
    enrollment = tf.begin_enrollment(user.user_id, user.username)
    secret = enrollment.secret
    tf.confirm_enrollment(user.user_id, _now_code(clock, secret))
    clock.advance(totp.PERIOD_S)
    # auth_max_failures_per_user is 2 in the test settings.
    assert not tf.verify_second_factor(user.user_id, "000000", IP)
    assert not tf.verify_second_factor(user.user_id, "000000", IP)
    # Now locked: even the correct current code is refused until the lockout passes.
    assert not tf.verify_second_factor(user.user_id, _now_code(clock, secret), IP)


# ---------------------------------------------------------------------- disable and recovery


def test_disable_removes_the_factor_and_recovery_codes(
    service: AuthService, tf: TwoFactorService, clock: FakeClock, user: Account
) -> None:
    _enable(tf, clock, user.user_id, user.username)
    tf.disable(user.user_id, "user")
    status = tf.status(user.user_id, "user")
    assert not status.enabled
    assert status.recovery_remaining == 0
    assert "2fa.disable" in {e.action for e in service.recent_audit()}


def test_disable_refused_when_the_policy_requires_it(service: AuthService, user: Account) -> None:
    tf = AuthService(
        service._db,
        service._clock,
        service._limiter,
        AuthSettings(auth_require_2fa="all"),
        service._passwords,
    ).two_factor
    enrollment = tf.begin_enrollment(user.user_id, user.username)
    tf.confirm_enrollment(user.user_id, _now_code(service._clock, enrollment.secret))
    with pytest.raises(Conflict):
        tf.disable(user.user_id, "user")
    assert tf.is_enabled(user.user_id)


def test_regenerate_recovery_codes_replaces_the_old_set(
    tf: TwoFactorService, clock: FakeClock, user: Account
) -> None:
    old = _enable(tf, clock, user.user_id, user.username)
    fresh = tf.regenerate_recovery_codes(user.user_id)
    assert set(fresh).isdisjoint(old)
    # An old code no longer works; a fresh one does.
    assert not tf.verify_second_factor(user.user_id, old[0], IP)
    assert tf.verify_second_factor(user.user_id, fresh[0], IP)


def test_regenerate_refused_without_enrollment(tf: TwoFactorService, user: Account) -> None:
    with pytest.raises(Conflict):
        tf.regenerate_recovery_codes(user.user_id)


def test_audit_and_events_never_carry_the_secret(
    service: AuthService,
    tf: TwoFactorService,
    clock: FakeClock,
    user: Account,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    enrollment = tf.begin_enrollment(user.user_id, user.username)
    secret = enrollment.secret
    codes = tf.confirm_enrollment(user.user_id, _now_code(clock, secret))
    clock.advance(totp.PERIOD_S)
    tf.verify_second_factor(user.user_id, codes[0], IP)  # recovery code success
    tf.verify_second_factor(user.user_id, "000000", IP)  # a wrong code
    # The audit log never mentions the secret or any recovery code.
    for entry in service.recent_audit():
        serialized = f"{entry.action} {entry.detail}"
        assert secret not in serialized
        assert all(code not in serialized for code in codes)
    # Every `auth.2fa` event carries the user id and a reason, never a secret or a code.
    events = collect(caplog, "auth.2fa")
    assert events
    assert all("reason" in e and e.get("user_id") == user.user_id for e in events)
    output = rendered(caplog)
    assert secret not in output
    assert all(code not in output for code in codes)
    assert "secret" not in output.lower() or "[REDACTED]" in output
