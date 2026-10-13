# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Optional TOTP second factor on the password logins (SPEC §7, docs/2fa.md).

TOTP (RFC 6238) is an **optional** second factor for the three password surfaces: the admin
panel login, the web player login and `POST /ut/v1/keys`. API-key auth (the Android app) is a
device token and stays single-factor, so the app keeps working unchanged.

`TwoFactorService` owns the enrollment, the login second step, the recovery codes and the
require-policy. It never checks the password itself (`AuthService.verify_password` does, with
its lockout) and never issues a session: a surface checks the password first, then, only when
the user has a second factor, calls `verify_second_factor` before issuing the session or the
device key.

Secrets at rest (SECURITY.md, docs/2fa.md): the TOTP shared secret must be reversible to
compute codes, so it cannot be a hash; it is **encrypted at rest** with Fernet
(`auth/secretbox.py`) under `UT_TOTP_ENCRYPTION_KEY`, so the database alone does not expose it.
Protect that key as well as the database. Without the key, enrollment and verification fail
closed. Recovery codes are stored only as Argon2id hashes and spent once. The shared secret,
the key and the recovery codes never reach a log line, an audit entry or an error; every
outcome is an `auth.2fa` security event with no secret.

Brute force: the second step has its own lockout bucket (`auth:2fa:<user id>`), so guessing a
six-digit code locks the user's second step after `UT_AUTH_MAX_FAILURES_PER_USER` tries for
`UT_AUTH_LOCKOUT_S`, on top of the password lockout in front.
"""

import logging
from dataclasses import dataclass
from logging import WARNING

from ultimatetunes.auth import totp
from ultimatetunes.auth.passwords import Passwords
from ultimatetunes.auth.repository import (
    AuditEntry,
    AuditRepository,
    RecoveryCode,
    RecoveryCodeRepository,
    UserTotp,
    UserTotpRepository,
    audit_detail,
)
from ultimatetunes.auth.secretbox import InvalidToken, SecretBox
from ultimatetunes.auth.settings import AuthSettings
from ultimatetunes.core.authn import Role
from ultimatetunes.core.clock import Clock, format_ts
from ultimatetunes.core.ratelimit import RateLimiter
from ultimatetunes.core.security_log import security_event
from ultimatetunes.db.database import Database
from ultimatetunes.errors import Conflict, FeatureDisabled
from ultimatetunes.ids import new_id

log = logging.getLogger(__name__)

ISSUER = "UltimateTunes"


def _bucket(user_id: str) -> str:
    return f"auth:2fa:{user_id}"


@dataclass(frozen=True)
class Status:
    """What a surface needs to decide the login and render the 2FA settings page."""

    enabled: bool
    pending: bool
    required: bool
    recovery_remaining: int

    @property
    def must_enroll(self) -> bool:
        """Policy covers this user but they have not turned a second factor on yet."""
        return self.required and not self.enabled


@dataclass(frozen=True)
class Enrollment:
    """A fresh, unconfirmed enrollment: what the QR code and the "enter the code" step need."""

    secret: str
    uri: str


class TwoFactorService:
    def __init__(
        self,
        db: Database,
        clock: Clock,
        limiter: RateLimiter,
        settings: AuthSettings,
        passwords: Passwords,
    ) -> None:
        self._db = db
        self._clock = clock
        self._limiter = limiter
        self._settings = settings
        self._passwords = passwords
        self._box = SecretBox(settings.totp_encryption_key)

    # ------------------------------------------------------------------ policy and status

    def requires(self, role: Role) -> bool:
        """Whether the server operator's `UT_AUTH_REQUIRE_2FA` policy covers this role."""
        policy = self._settings.auth_require_2fa
        return policy == "all" or (policy == "admins" and role == "admin")

    def _row(self, user_id: str) -> UserTotp | None:
        with self._db.read() as conn:
            return UserTotpRepository(conn).get(user_id)

    def is_enabled(self, user_id: str) -> bool:
        row = self._row(user_id)
        return row is not None and row.enabled

    def status(self, user_id: str, role: Role) -> Status:
        with self._db.read() as conn:
            row = UserTotpRepository(conn).get(user_id)
            remaining = RecoveryCodeRepository(conn).count_unused(user_id)
        enabled = row is not None and row.enabled
        return Status(
            enabled=enabled,
            pending=row is not None and not row.enabled,
            required=self.requires(role),
            recovery_remaining=remaining if enabled else 0,
        )

    # ------------------------------------------------------------------ enrollment

    def begin_enrollment(self, user_id: str, username: str) -> Enrollment:
        """A fresh secret for `user_id`, encrypted and stored unconfirmed, with its `otpauth://`
        URI. Refused when a second factor is already on (disable it first), and fails closed
        with a clear operator error when no encryption key is configured."""
        now = format_ts(self._clock.now())
        secret = totp.generate_secret()
        sealed = self._box.encrypt(secret)  # FeatureDisabled when UT_TOTP_ENCRYPTION_KEY is unset
        with self._db.transaction() as conn:
            repo = UserTotpRepository(conn)
            existing = repo.get(user_id)
            if existing is not None and existing.enabled:
                raise Conflict("Two-factor authentication is already enabled")
            repo.upsert_secret(user_id, sealed, now)
        return Enrollment(secret=secret, uri=totp.otpauth_uri(secret, username, ISSUER))

    def pending_enrollment(self, user_id: str, username: str) -> Enrollment | None:
        """The stored, not-yet-confirmed enrollment of `user_id` (to re-render the setup page
        without minting a new secret), or None when there is none or it is already enabled."""
        row = self._row(user_id)
        if row is None or row.enabled:
            return None
        secret = self._box.decrypt(row.secret)
        return Enrollment(secret=secret, uri=totp.otpauth_uri(secret, username, ISSUER))

    def confirm_enrollment(self, user_id: str, code: str) -> list[str]:
        """Turns the pending enrollment on once `code` proves the secret was scanned, and
        returns the one-time recovery codes (shown once). Raises `Conflict` when there is
        nothing to confirm or the code is wrong."""
        now_dt = self._clock.now()
        now = format_ts(now_dt)
        with self._db.transaction() as conn:
            repo = UserTotpRepository(conn)
            row = repo.get(user_id)
            if row is None or row.enabled:
                raise Conflict("Start the two-factor setup first")
            step = totp.verify(
                self._box.decrypt(row.secret),
                code,
                int(now_dt.timestamp()),
                window=self._settings.auth_2fa_window,
            )
            if step is None:
                self._event("confirm_bad_code", user_id)
                raise Conflict("That code is wrong or has expired, try the current one")
            repo.enable(user_id, step, now)
            codes = self._reset_recovery_codes(conn, user_id, now)
            self._audit(conn, user_id, "2fa.enable")
        self._event("enabled", user_id, level=logging.INFO)
        return codes

    def _reset_recovery_codes(self, conn: object, user_id: str, now: str) -> list[str]:
        repo = RecoveryCodeRepository(conn)  # type: ignore[arg-type]
        repo.delete_all(user_id)
        codes = totp.generate_recovery_codes()
        for clear in codes:
            repo.insert(
                RecoveryCode(
                    id=new_id(self._clock),
                    user_id=user_id,
                    code_hash=self._passwords.hash(totp.normalize_recovery_code(clear)),
                    created_at=now,
                    used_at=None,
                )
            )
        return codes

    def regenerate_recovery_codes(self, user_id: str) -> list[str]:
        """New recovery codes for an enabled user; the old ones stop working. Shown once."""
        now = format_ts(self._clock.now())
        with self._db.transaction() as conn:
            row = UserTotpRepository(conn).get(user_id)
            if row is None or not row.enabled:
                raise Conflict("Enable two-factor authentication first")
            codes = self._reset_recovery_codes(conn, user_id, now)
            self._audit(conn, user_id, "2fa.recovery_regenerate")
        return codes

    def disable(self, user_id: str, role: Role) -> None:
        """Removes the second factor and every recovery code. Refused while the policy requires
        it for this role (the caller re-checks the password before calling)."""
        if self.requires(role):
            raise Conflict("Two-factor authentication is required for this account")
        with self._db.transaction() as conn:
            UserTotpRepository(conn).delete(user_id)
            RecoveryCodeRepository(conn).delete_all(user_id)
            self._audit(conn, user_id, "2fa.disable")
        self._event("disabled", user_id, level=logging.INFO)

    # ------------------------------------------------------------------ login second step

    def verify_second_factor(self, user_id: str, code: str, client_ip: str | None) -> bool:
        """The login second step: True when `code` is this user's current TOTP code or an
        unused recovery code. Fails closed on an empty, wrong or replayed code, counts the
        failure against the per-user 2FA lockout, and never logs the code."""
        bucket = _bucket(user_id)
        if not self._limiter.locked(bucket).allowed:
            self._event("locked", user_id, client_ip=client_ip)
            return False
        submitted = (code or "").strip()
        row = self._row(user_id)
        if row is None or not row.enabled:
            # Nothing to verify: fail closed without leaking whether the user has a factor.
            self._fail(bucket, user_id, client_ip, "not_enrolled")
            return False
        if submitted and submitted.replace(" ", "").isdigit():
            matched = self._check_totp(row, submitted, user_id)
        else:
            matched = self._check_recovery(user_id, submitted)
        if matched is None:
            self._fail(bucket, user_id, client_ip, "bad_code")
            return False
        self._limiter.record_success(bucket)
        self._event(matched, user_id, client_ip=client_ip, level=logging.INFO)
        return True

    def _check_totp(self, row: UserTotp, code: str, user_id: str) -> str | None:
        try:
            secret = self._box.decrypt(row.secret)
        except (InvalidToken, FeatureDisabled):
            # Wrong or missing UT_TOTP_ENCRYPTION_KEY: fail closed, never accept blindly.
            self._event("secret_unavailable", user_id)
            return None
        step = totp.verify(
            secret,
            code,
            int(self._clock.now().timestamp()),
            window=self._settings.auth_2fa_window,
        )
        if step is None:
            return None
        # Claim the step atomically: two concurrent valid requests cannot both win it (no replay).
        with self._db.transaction() as conn:
            if not UserTotpRepository(conn).claim_step(user_id, step):
                return None
        return "totp_ok"

    def _check_recovery(self, user_id: str, code: str) -> str | None:
        normalized = totp.normalize_recovery_code(code)
        if not normalized:
            return None
        now = format_ts(self._clock.now())
        with self._db.read() as conn:
            candidates = RecoveryCodeRepository(conn).unused_of(user_id)
        hit: RecoveryCode | None = None
        # Check every candidate (no early stop) so timing does not reveal the position.
        for candidate in candidates:
            if self._passwords.verify(candidate.code_hash, normalized):
                hit = candidate
        if hit is None:
            return None
        with self._db.transaction() as conn:
            if not RecoveryCodeRepository(conn).mark_used(hit.id, now):
                return None  # raced to the same code; treat as spent
            self._audit(conn, user_id, "2fa.recovery_used")
        return "recovery_ok"

    def _fail(self, bucket: str, user_id: str, client_ip: str | None, reason: str) -> None:
        self._limiter.record_failure(
            bucket,
            max_failures=self._settings.auth_max_failures_per_user,
            lockout_s=self._settings.auth_lockout_s,
        )
        self._event(reason, user_id, client_ip=client_ip)

    # ------------------------------------------------------------------ logging and audit

    def _event(
        self, reason: str, user_id: str, *, client_ip: str | None = None, level: int = WARNING
    ) -> None:
        security_event("auth.2fa", level=level, reason=reason, user_id=user_id, client_ip=client_ip)

    def _audit(self, conn: object, user_id: str, action: str) -> None:
        AuditRepository(conn).add(  # type: ignore[arg-type]
            AuditEntry(
                id=new_id(self._clock),
                occurred_at=format_ts(self._clock.now()),
                actor_user_id=user_id,
                actor_ip=None,
                action=action,
                target_type="user",
                target_id=user_id,
                detail=audit_detail(None),
            )
        )
