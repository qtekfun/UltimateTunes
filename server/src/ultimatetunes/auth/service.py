# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Users, API keys and authentication (SPEC RF-01, RF-02; contracts/errors.md).

`AuthService` is the one place that checks credentials. It implements `core.authn.Authenticator`
for the routers and gives the admin panel (T15) and the CLI what they need: users (create,
disable, role, password), keys (create, list, revoke) and the audit log.

Rules on `/rest` (contracts/openapi/opensubsonic-subset.yaml):
- `apiKey` alone; with `u`, `p`, `t` or `s` it is error 43; unknown, malformed or revoked: 44.
- `t`/`s` token auth: error 42 (only Argon2id hashes are kept).
- `u` + `p` (clear or `enc:` hex): `p` must be an API key **of that user**; account passwords
  are never accepted there. Anything wrong is error 40, whatever the reason.
- Nothing usable: error 10.
On `/ut/v1`: `X-Api-Key` or `apiKey`, both only when equal (`conflicting_auth`).

Rate limit and lockout (`core.ratelimit`):
- Every request with a valid key takes a token from `auth:key:<id>`.
- Failures (40, 44, 50) count per IP (`auth:ip:<ip>`), and password failures also per username.
  Reaching the limit locks the IP bucket for `auth_lockout_s`. The per-username count is
  **split by origin** (`trusted` of `verify_password`): `auth:user:<name>` for checks from the
  admin's own networks (LAN/Tailscale, `core.forwarded.from_trusted_network`), locked like the
  IP bucket, and `auth:user-out:<name>` for everything else (the web player's sign-in and
  `POST /ut/v1/keys` from the Internet). The outside counter is **never a hard lock**: each
  consecutive failure delays the next check of that username from outside
  (`auth_outside_backoff_base_s`, doubling, at most `auth_outside_backoff_max_s`; a success
  resets it). The attempt is reserved (counted and the next delay started) atomically before
  Argon2 runs, so concurrent attempts get one guess per delay window, not one each. Strangers
  can keep slowing a family member's outside sign-in down, but never touch the inside counter,
  existing sessions or API keys, so LAN/Tailscale sign-ins always work. A key that
  exists but is revoked or belongs to a disabled user is refused without counting (a stale
  device is not guessing), so it never locks out its IP.
- Password checks need the client address: without one they are refused (`Forbidden`), so
  anonymous callers never share one lockout bucket. A reverse proxy must forward client IPs.
- A locked IP gets 429 instead of 40/44 for bad credentials, and password checks are refused
  before Argon2 runs. A **valid API key is never refused for its IP's lockout**: one stale device
  behind a shared home IP must not lock out the whole household, and a 256-bit key cannot be
  guessed, so the lockout there only stops the noise.
- Password checks also take a token from `auth:login:<ip>`.
- IPv6 clients are counted by their /64 (`throttle.client_key`), at most
  `auth_argon2_concurrency` Argon2 verifications run at once (`throttle.Argon2Slots`), and a
  global failure budget per minute (`auth:global`) locks unknown keys, and outside password
  checks of usernames with outside failures on record, while it is exceeded (auth/throttle.py).
  A username that has not failed from outside since its last success is never refused by it:
  a password spray cannot deny the web sign-in of everyone else. Password checks from the
  admin's own networks (`trusted`) are neither refused by it nor counted in it.

Every outcome is also a structured security event (`core/security_log.py`, docs/logging.md):
`auth.failure` (with a `reason`), `auth.throttled` (refused by a lock, a delay or a rate before
anything is checked), `auth.lockout` and `auth.success` (password sign-ins; an API key when its
`last_used_at` is written, at most once a minute per key and address).

Secrets (keys, passwords, hashes) never reach a log line, an audit entry or an error message.
"""

import logging
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from functools import partial
from logging import WARNING
from typing import TYPE_CHECKING, NoReturn

from ultimatetunes.auth import keys
from ultimatetunes.auth.passwords import Passwords, check_policy
from ultimatetunes.auth.repository import (
    ApiKey,
    ApiKeyRepository,
    AuditEntry,
    AuditRepository,
    KeyOwner,
    SessionEpochRepository,
    User,
    UserRepository,
    audit_detail,
)
from ultimatetunes.auth.settings import AuthSettings
from ultimatetunes.auth.throttle import Argon2Slots, client_key, shared_slots
from ultimatetunes.core.authn import Principal, Role
from ultimatetunes.core.clock import Clock, format_ts, parse_ts
from ultimatetunes.core.ratelimit import Limit, RateLimiter, backoff_delay
from ultimatetunes.core.security_log import emit, security_event
from ultimatetunes.db.database import Database
from ultimatetunes.db.driver import Connection, IntegrityError
from ultimatetunes.errors import (
    AccountDisabled,
    AuthenticationFailed,
    AuthenticationRequired,
    Conflict,
    ConflictingAuth,
    Forbidden,
    InvalidApiKey,
    InvalidParameter,
    NotFound,
    RateLimited,
    TokenAuthNotSupported,
    TunesError,
)
from ultimatetunes.ids import new_id

if TYPE_CHECKING:
    from ultimatetunes.core.services import Services

log = logging.getLogger(__name__)

# Where a client learns how to get an API key (contracts/errors.md: `helpUrl` of 42 and 44).
HELP_URL = "https://github.com/qtekfun/UltimateTunes#api-keys"
# `last_used_at`/`last_used_ip` are written at most this often per key (one write per request
# would serialize every request on the single SQLite writer).
TOUCH_EVERY_S = 60
ROLES: tuple[Role, ...] = ("admin", "user")
_USERNAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
MAX_KEY_NAME = 100
# Session epochs of the admin panel and the web player (`admin/routes.py`, `web/security.py`):
# "sign out every device" raises both.
# The one definition of those keys: `admin/routes.py` and `web/security.py` import them.
ADMIN_EPOCH_PREFIX = "admin.session_epoch."
WEB_EPOCH_PREFIX = "web.session_epoch."
SESSION_EPOCH_PREFIXES = (ADMIN_EPOCH_PREFIX, WEB_EPOCH_PREFIX)
# The global failure budget (auth/throttle.py): its token bucket, and the lock it sets.
GLOBAL_FAILURES = "auth:global:failures"
GLOBAL_LOCK = "auth:global"
# `reason` of `auth.throttled` for each kind of lock bucket (`auth:<kind>:...`).
LOCK_REASONS = {"ip": "ip_locked", "user": "user_locked", "global": "global_lock"}
# What an `auth.failure` was about (`credential` field).
CREDENTIAL_KEY = "api_key"
CREDENTIAL_ACCOUNT = "password"
CREDENTIAL_SUBSONIC = "subsonic_password"


def _failure(reason: str, client_ip: str | None, **fields: str | bool | None) -> None:
    emit("auth.failure", {"reason": reason, "client_ip": client_ip, **fields}, level=WARNING)


def _throttled(reason: str, client_ip: str | None, **fields: str | int | None) -> None:
    emit("auth.throttled", {"reason": reason, "client_ip": client_ip, **fields}, level=WARNING)


def normalize_username(username: str) -> str:
    """Usernames are case-insensitive: stored and looked up in lower case."""
    return username.strip().lower()


def check_username(username: str) -> str:
    name = normalize_username(username)
    if not _USERNAME.fullmatch(name):
        raise InvalidParameter(
            "The username must have 1 to 64 characters: letters, digits, '.', '_' or '-'"
        )
    return name


def check_key_name(name: str) -> str:
    cleaned = name.strip()
    if not 1 <= len(cleaned) <= MAX_KEY_NAME or not cleaned.isprintable():
        raise InvalidParameter(f"The device name must have 1 to {MAX_KEY_NAME} characters")
    return cleaned


def _first(params: Mapping[str, Sequence[str]], name: str) -> str | None:
    """The first value of a parameter; an empty value counts as absent."""
    values = params.get(name)
    return values[0] if values and values[0] else None


def _role(value: str) -> Role:
    for role in ROLES:
        if value == role:
            return role
    raise InvalidParameter("The role must be admin or user")


@dataclass(frozen=True)
class AuditEvent:
    """What an audit entry records besides who, from where and when. No secrets in `detail`."""

    action: str
    target_type: str | None = None
    target_id: str | None = None
    detail: dict[str, object] | None = None


@dataclass(frozen=True)
class CreatedKey:
    key: ApiKey
    # The full key: returned once to the caller, never stored, logged or shown by repr.
    secret: str = field(repr=False)


class AuthService:
    def __init__(  # noqa: PLR0913 - the shared services it checks credentials with
        self,
        db: Database,
        clock: Clock,
        limiter: RateLimiter,
        settings: AuthSettings | None = None,
        passwords: Passwords | None = None,
        *,
        slots: Argon2Slots | None = None,
    ) -> None:
        self._db = db
        self._clock = clock
        self._limiter = limiter
        self._settings = settings or AuthSettings()
        self._passwords = passwords or Passwords()
        self._slots = slots or shared_slots()

    @classmethod
    def from_services(
        cls, services: "Services", passwords: Passwords | None = None
    ) -> "AuthService":
        return cls(services.db, services.clock, services.rate_limiter, passwords=passwords)

    # ------------------------------------------------------------------ Authenticator

    def authenticate_subsonic(
        self, params: Mapping[str, Sequence[str]], client_ip: str | None
    ) -> Principal:
        api_key = _first(params, "apiKey")
        username, password = _first(params, "u"), _first(params, "p")
        token, salt = _first(params, "t"), _first(params, "s")
        if api_key is not None:
            if username or password or token or salt:
                _failure("conflicting_auth", client_ip, credential=CREDENTIAL_KEY)
                raise ConflictingAuth()
            return self._by_key(api_key, client_ip, InvalidApiKey(help_url=HELP_URL))
        if token is not None or salt is not None:
            _failure("token_auth", client_ip, user=username, credential=CREDENTIAL_SUBSONIC)
            raise TokenAuthNotSupported(help_url=HELP_URL)
        if username is None or password is None:
            _failure("missing_credentials", client_ip, user=username)
            raise AuthenticationRequired()
        key = keys.decode_password(password)
        return self._by_key(
            key or "", client_ip, AuthenticationFailed(), username=normalize_username(username)
        )

    def authenticate_api_key(
        self, header_key: str | None, query_key: str | None, client_ip: str | None
    ) -> Principal:
        key = self._one_key(header_key, query_key, client_ip)
        if key is None:
            _failure("missing_credentials", client_ip)
            raise AuthenticationRequired()
        return self._by_key(key, client_ip, InvalidApiKey())

    @staticmethod
    def _one_key(
        header_key: str | None, query_key: str | None, client_ip: str | None
    ) -> str | None:
        if header_key and query_key and header_key != query_key:
            _failure("conflicting_auth", client_ip, credential=CREDENTIAL_KEY)
            raise ConflictingAuth()
        return header_key or query_key or None

    def _owner(self, key: str) -> KeyOwner | None:
        if not keys.is_well_formed(key):
            return None
        with self._db.read() as conn:
            return ApiKeyRepository(conn).owner_by_hash(keys.digest(key))

    @staticmethod
    def _principal(owner: KeyOwner) -> Principal:
        return Principal(owner.user_id, owner.username, _role(owner.role), owner.key_id)

    def _by_key(
        self,
        key: str,
        client_ip: str | None,
        invalid: TunesError,
        *,
        username: str | None = None,
    ) -> Principal:
        owner = self._owner(key)
        if owner is None or (username is not None and owner.username != username):
            self._refuse_locked(self._ip_bucket(client_ip), client_ip=client_ip)
            self._refuse_global(trusted=False, client_ip=client_ip)
            if username is None:
                _failure("invalid_key", client_ip, credential=CREDENTIAL_KEY)
            else:
                _failure(
                    "bad_credentials", client_ip, user=username, credential=CREDENTIAL_SUBSONIC
                )
            self._fail(invalid, client_ip)
        if owner.revoked_at is not None or owner.is_disabled:
            # A real key, revoked or of a disabled user: a stale device, not a guess. Refused
            # (429 while the IP is locked) but never counted, so it cannot lock out its IP.
            self._refuse_locked(self._ip_bucket(client_ip), client_ip=client_ip)
            revoked = owner.revoked_at is not None
            _failure(
                "revoked_key" if revoked else "account_disabled",
                client_ip,
                user=owner.username,
                key_id=owner.key_id,
                credential=CREDENTIAL_KEY,
            )
            raise invalid if revoked else AccountDisabled()
        limit = Limit(self._settings.auth_key_rate_per_s, self._settings.auth_key_burst)
        decision = self._limiter.hit(f"auth:key:{owner.key_id}", limit)
        if not decision.allowed:
            _throttled("key_rate", client_ip, user=owner.username, key_id=owner.key_id)
            raise RateLimited(decision.retry_after_s)
        self._touch(owner, client_ip)
        return self._principal(owner)

    def _touch(self, owner: KeyOwner, client_ip: str | None) -> None:
        now = self._clock.now()
        fresh = (
            owner.last_used_at is not None
            and owner.last_used_ip == client_ip
            and now - parse_ts(owner.last_used_at) < timedelta(seconds=TOUCH_EVERY_S)
        )
        if not fresh:
            with self._db.transaction() as conn:
                ApiKeyRepository(conn).touch(owner.key_id, format_ts(now), client_ip)
            security_event(
                "auth.success",
                client_ip=client_ip,
                user=owner.username,
                user_id=owner.user_id,
                key_id=owner.key_id,
                credential=CREDENTIAL_KEY,
            )

    # ------------------------------------------------------------------ lockout

    @staticmethod
    def _ip_bucket(client_ip: str | None) -> str:
        return f"auth:ip:{client_key(client_ip)}"

    @staticmethod
    def _user_bucket(username: str, *, trusted: bool) -> str:
        """The per-username lockout counter of the caller's origin: failures from outside the
        admin's networks never lock logins from inside them (an admin locked out by strangers)."""
        return f"auth:user:{username}" if trusted else f"auth:user-out:{username}"

    def _refuse_locked(self, *buckets: str, client_ip: str | None) -> None:
        for bucket in buckets:
            decision = self._limiter.locked(bucket)
            if not decision.allowed:
                kind, _, target = bucket.removeprefix("auth:").partition(":")
                _throttled(
                    LOCK_REASONS.get(kind, "locked"),
                    client_ip,
                    user=target if kind == "user" else None,
                    retry_after_s=decision.retry_after_s,
                )
                raise RateLimited(decision.retry_after_s)

    def _fail(
        self,
        error: TunesError,
        client_ip: str | None,
        user_bucket: str | None = None,
        *,
        trusted: bool = False,
    ) -> NoReturn:
        """Counts the failure (per IP, and in `user_bucket` for passwords), then raises `error`.
        Locking a bucket is logged and audited."""
        buckets = [(self._ip_bucket(client_ip), self._settings.auth_max_failures_per_ip)]
        if user_bucket is not None and trusted:
            buckets.append((user_bucket, self._settings.auth_max_failures_per_user))
        for bucket, max_failures in buckets:
            decision = self._limiter.record_failure(
                bucket, max_failures=max_failures, lockout_s=self._settings.auth_lockout_s
            )
            if not decision.allowed:
                self._log_lockout(bucket, client_ip, decision.retry_after_s)
        if user_bucket is not None and not trusted:
            # The failure was already counted when the attempt was reserved (`_reserve`).
            failures = self._limiter.failures(user_bucket)
            if failures == self._settings.auth_max_failures_per_user:
                self._log_lockout(user_bucket, client_ip, self._outside_delay_s(failures))
        if not trusted:
            self._count_global_failure(client_ip)
        raise error

    def _log_lockout(self, bucket: str, client_ip: str | None, seconds: int) -> None:
        _, kind, target = bucket.split(":", 2)
        security_event(
            "auth.lockout",
            level=logging.WARNING,
            message=f"auth lockout of {kind} {target} for {seconds} s",
            client_ip=client_ip,
            scope=kind,
            target=target,
            user=None if kind == "ip" else target,
            duration_s=seconds,
        )
        self._audit(None, client_ip, AuditEvent("auth.lockout", kind, target))

    def _outside_delay_s(self, failures: int) -> int:
        delay = backoff_delay(
            failures,
            base_s=self._settings.auth_outside_backoff_base_s,
            max_s=self._settings.auth_outside_backoff_max_s,
        )
        return max(1, math.ceil(delay))

    def _reserve(self, user_bucket: str, client_ip: str | None, *, trusted: bool) -> None:
        """The per-username gate, right before Argon2 (module doc). Inside: refused while the
        username is locked. Outside: the attempt is reserved atomically (`reserve_backoff`:
        refused while the delay runs, else counted as a failure and the next delay started), so
        however many attempts arrive when a delay ends, only one reaches Argon2; a success
        clears it."""
        if trusted:
            self._refuse_locked(user_bucket, client_ip=client_ip)
            return
        decision = self._limiter.reserve_backoff(
            user_bucket,
            base_s=self._settings.auth_outside_backoff_base_s,
            max_s=self._settings.auth_outside_backoff_max_s,
        )
        if not decision.allowed:
            _throttled(
                "user_backoff",
                client_ip,
                user=user_bucket.split(":", 2)[2],
                retry_after_s=decision.retry_after_s,
            )
            raise RateLimited(decision.retry_after_s)

    def _refuse_global(self, *, trusted: bool, client_ip: str | None) -> None:
        """429 while the global failure budget is locked, except for the admin's own networks
        (module doc): strangers can never lock an admin out of LAN/Tailscale logins."""
        if not trusted:
            self._refuse_locked(GLOBAL_LOCK, client_ip=client_ip)

    def _count_global_failure(self, client_ip: str | None) -> None:
        """One failure of the global budget; past it, `auth:global` is locked (module doc)."""
        per_min = self._settings.auth_max_failures_global_per_min
        if self._limiter.hit(GLOBAL_FAILURES, Limit(per_min / 60, per_min)).allowed:
            return
        lockout_s = self._settings.auth_global_lockout_s
        self._limiter.record_failure(GLOBAL_LOCK, max_failures=1, lockout_s=lockout_s)
        security_event(
            "auth.lockout",
            level=logging.WARNING,
            message=f"auth lockout of everyone for {lockout_s} s: too many failures",
            client_ip=client_ip,
            scope="global",
            duration_s=lockout_s,
        )
        self._audit(None, client_ip, AuditEvent("auth.lockout", "global", None))

    def _password_matches(
        self, user: User | None, password: str, reserve: Callable[[], None]
    ) -> bool:
        """Argon2 under a slot (auth/throttle.py); an unknown user burns the same time.
        `reserve` runs once the slot is held, so a busy server never costs an attempt."""
        with self._slots.slot():
            reserve()
            if user is None:
                self._passwords.burn(password)
                return False
            return self._passwords.verify(user.password_hash, password)

    # ------------------------------------------------------------------ passwords

    def verify_password(
        self, username: str, password: str, client_ip: str | None, *, trusted: bool = False
    ) -> User:
        """Checks an account password (admin panel login, `POST /ut/v1/keys`). Wrong password
        and unknown user give the same `AuthenticationFailed` in the same time. `trusted`: the
        request comes from the admin's own networks (`core.forwarded.trusted_origin`); it picks
        the per-username counter (inside: lockout; outside: growing delay, module docstring),
        and such checks are neither refused by the global failure budget nor counted in it."""
        name = normalize_username(username)
        if not client_ip:
            _failure("no_client_address", client_ip, user=name, credential=CREDENTIAL_ACCOUNT)
            raise Forbidden("Password checks need the client address")
        user_bucket = self._user_bucket(name, trusted=trusted)
        self._refuse_locked(self._ip_bucket(client_ip), client_ip=client_ip)
        if trusted:
            self._refuse_locked(user_bucket, client_ip=client_ip)
        # The global budget only holds back usernames that failed from outside (module doc).
        self._refuse_global(
            trusted=trusted or self._limiter.failures(user_bucket) == 0, client_ip=client_ip
        )
        limit = Limit(self._settings.auth_login_rate_per_s, self._settings.auth_login_burst)
        decision = self._limiter.hit(f"auth:login:{client_key(client_ip)}", limit)
        if not decision.allowed:
            _throttled("login_rate", client_ip, user=name, retry_after_s=decision.retry_after_s)
            raise RateLimited(decision.retry_after_s)
        with self._db.read() as conn:
            user = UserRepository(conn).by_username(name)
        reserve = partial(self._reserve, user_bucket, client_ip, trusted=trusted)
        if not self._password_matches(user, password, reserve) or user is None:
            _failure(
                "bad_password",
                client_ip,
                user=name,
                known_user=user is not None,
                trusted=trusted,
                credential=CREDENTIAL_ACCOUNT,
            )
            self._fail(AuthenticationFailed(), client_ip, user_bucket, trusted=trusted)
        if user.is_disabled:
            _failure(
                "account_disabled",
                client_ip,
                user=name,
                trusted=trusted,
                credential=CREDENTIAL_ACCOUNT,
            )
            self._fail(AccountDisabled(), client_ip, user_bucket, trusted=trusted)
        self._limiter.record_success(self._ip_bucket(client_ip))
        self._limiter.record_success(user_bucket)
        security_event(
            "auth.success",
            client_ip=client_ip,
            user=name,
            user_id=user.id,
            trusted=trusted,
            credential=CREDENTIAL_ACCOUNT,
        )
        new_hash = (
            self._passwords.hash(password)
            if self._passwords.needs_rehash(user.password_hash)
            else None
        )
        now = format_ts(self._clock.now())
        with self._db.transaction() as conn:
            users = UserRepository(conn)
            users.touch_login(user.id, now)
            if new_hash is not None:
                users.set_password_hash(user.id, new_hash, now)
        return user

    # ------------------------------------------------------------------ users

    def create_user(
        self,
        username: str,
        password: str,
        role: str,
        *,
        actor: Principal | None,
        client_ip: str | None = None,
    ) -> User:
        name = check_username(username)
        check_policy(password)
        user = self._new_user(name, password, _role(role))
        with self._db.transaction() as conn:
            self._insert_user(conn, user, actor, client_ip)
        return user

    def bootstrap_admin(self, username: str, password: str, client_ip: str | None = None) -> bool:
        """Creates the first admin, only while there is no user at all. False when users exist
        (nothing changes: a bootstrap never resets a password)."""
        name = check_username(username)
        check_policy(password)
        user = self._new_user(name, password, "admin")
        with self._db.transaction() as conn:
            if UserRepository(conn).count() > 0:
                return False
            self._insert_user(conn, user, None, client_ip)
        return True

    def _new_user(self, name: str, password: str, role: Role) -> User:
        """Hashes outside the write transaction: Argon2 must not hold the single writer."""
        now = format_ts(self._clock.now())
        password_hash = self._passwords.hash(password)
        return User(new_id(self._clock), name, password_hash, role, False, now, now, None)

    def _insert_user(
        self, conn: Connection, user: User, actor: Principal | None, client_ip: str | None
    ) -> None:
        users = UserRepository(conn)
        if users.by_username(user.username) is not None:
            raise Conflict("That username is taken")
        users.insert(user)
        detail: dict[str, object] = {"username": user.username, "role": user.role}
        self._audit_in(conn, actor, client_ip, AuditEvent("user.create", "user", user.id, detail))
        log.info("user %s created with role %s", user.id, user.role)

    def get_user(self, user_id: str) -> User:
        with self._db.read() as conn:
            user = UserRepository(conn).get(user_id)
        if user is None:
            raise NotFound("No such user")
        return user

    def list_users(self) -> list[User]:
        with self._db.read() as conn:
            return UserRepository(conn).all_users()

    def set_password(
        self, user_id: str, password: str, *, actor: Principal | None, client_ip: str | None = None
    ) -> None:
        check_policy(password)
        password_hash = self._passwords.hash(password)
        self._update_user(
            user_id,
            lambda users, now: users.set_password_hash(user_id, password_hash, now),
            AuditEvent("user.password", "user", user_id),
            actor,
            client_ip,
        )

    def set_disabled(
        self, user_id: str, disabled: bool, *, actor: Principal | None, client_ip: str | None = None
    ) -> None:
        """A disabled user keeps its keys, but every request with them gets error 50."""
        self._update_user(
            user_id,
            lambda users, now: users.set_disabled(user_id, disabled, now),
            AuditEvent("user.disable" if disabled else "user.enable", "user", user_id),
            actor,
            client_ip,
        )

    def set_role(
        self, user_id: str, role: str, *, actor: Principal | None, client_ip: str | None = None
    ) -> None:
        checked = _role(role)
        self._update_user(
            user_id,
            lambda users, now: users.set_role(user_id, checked, now),
            AuditEvent("user.role", "user", user_id, {"role": checked}),
            actor,
            client_ip,
        )

    def _update_user(
        self,
        user_id: str,
        change: Callable[[UserRepository, str], int],
        event: AuditEvent,
        actor: Principal | None,
        client_ip: str | None,
    ) -> None:
        now = format_ts(self._clock.now())
        with self._db.transaction() as conn:
            if change(UserRepository(conn), now) == 0:
                raise NotFound("No such user")
            self._audit_in(conn, actor, client_ip, event)

    # ------------------------------------------------------------------ keys

    def create_key(
        self, user_id: str, name: str, *, actor: Principal | None, client_ip: str | None = None
    ) -> CreatedKey:
        """A new key for `user_id` (admin panel, or `create_key_with_password`)."""
        device = check_key_name(name)
        secret = keys.generate()
        now = format_ts(self._clock.now())
        key = ApiKey(
            new_id(self._clock), user_id, device, keys.prefix(secret), now, None, None, None
        )
        with self._db.transaction() as conn:
            if UserRepository(conn).get(user_id) is None:
                raise NotFound("No such user")
            try:
                ApiKeyRepository(conn).insert(key, keys.digest(secret))
            except IntegrityError as exc:
                # 256 random bits never collide; refuse rather than reuse a hash.
                raise Conflict("Could not create the key, try again") from exc
            event = AuditEvent("key.create", "api_key", key.id, {"name": device})
            self._audit_in(conn, actor, client_ip, event)
        log.info("api key %s created for user %s", key.id, user_id)
        return CreatedKey(key, secret)

    def create_key_with_password(  # noqa: PLR0913 - the fields of the request and its origin
        self,
        username: str,
        password: str,
        name: str,
        client_ip: str | None,
        presented_key: str | None = None,
        *,
        trusted: bool = False,
    ) -> CreatedKey:
        """`POST /ut/v1/keys`: username and password, no key needed. A key sent along must be
        valid and belong to the same user (`conflicting_auth` otherwise). `trusted`: as in
        `verify_password`."""
        check_key_name(name)
        presenter = (
            None
            if presented_key is None
            else self._by_key(presented_key, client_ip, InvalidApiKey())
        )
        user = self.verify_password(username, password, client_ip, trusted=trusted)
        if presenter is not None and presenter.user_id != user.id:
            _failure("conflicting_auth", client_ip, user=user.username, credential=CREDENTIAL_KEY)
            raise ConflictingAuth()
        actor = Principal(user.id, user.username, _role(user.role))
        return self.create_key(user.id, name, actor=actor, client_ip=client_ip)

    def list_keys(self, user_id: str) -> list[ApiKey]:
        with self._db.read() as conn:
            return ApiKeyRepository(conn).of_user(user_id)

    def revoke_own_key(self, principal: Principal, key_id: str, client_ip: str | None) -> None:
        """`DELETE /ut/v1/keys/{keyId}`: only the caller's keys; someone else's is not found.
        Idempotent."""
        with self._db.read() as conn:
            key = ApiKeyRepository(conn).get(key_id)
        if key is None or key.user_id != principal.user_id:
            raise NotFound("No such key")
        self.revoke_key(key_id, actor=principal, client_ip=client_ip)

    def revoke_key(
        self, key_id: str, *, actor: Principal | None, client_ip: str | None = None
    ) -> None:
        """Any key (admin panel). Revoking a revoked key changes nothing and is not an error."""
        now = format_ts(self._clock.now())
        with self._db.transaction() as conn:
            repo = ApiKeyRepository(conn)
            if repo.get(key_id) is None:
                raise NotFound("No such key")
            if repo.revoke(key_id, now):
                self._audit_in(conn, actor, client_ip, AuditEvent("key.revoke", "api_key", key_id))
                log.info("api key %s revoked", key_id)

    def sign_out_everywhere(
        self, user_id: str, *, actor: Principal, client_ip: str | None = None
    ) -> int:
        """Revokes every API key of `user_id` and ends every admin and web session of it
        (copied cookies included), in one transaction, audited. Only for the user itself or an
        admin (`Forbidden` otherwise). Returns how many keys were revoked."""
        if actor.user_id != user_id and actor.role != "admin":
            raise Forbidden("Only an administrator can sign out another user")
        now = format_ts(self._clock.now())
        with self._db.transaction() as conn:
            if UserRepository(conn).get(user_id) is None:
                raise NotFound("No such user")
            revoked = ApiKeyRepository(conn).revoke_all(user_id, now)
            epochs = SessionEpochRepository(conn)
            for prefix in SESSION_EPOCH_PREFIXES:
                epochs.bump(prefix + user_id, now)
            event = AuditEvent("user.sign_out_all", "user", user_id, {"keys": revoked})
            self._audit_in(conn, actor, client_ip, event)
        log.info("user %s signed out everywhere (%d keys revoked)", user_id, revoked)
        return revoked

    # ------------------------------------------------------------------ audit

    def recent_audit(self, limit: int = 100) -> list[AuditEntry]:
        with self._db.read() as conn:
            return AuditRepository(conn).recent(limit)

    def _audit(self, actor: Principal | None, client_ip: str | None, event: AuditEvent) -> None:
        with self._db.transaction() as conn:
            self._audit_in(conn, actor, client_ip, event)

    def _audit_in(
        self, conn: Connection, actor: Principal | None, client_ip: str | None, event: AuditEvent
    ) -> None:
        AuditRepository(conn).add(
            AuditEntry(
                id=new_id(self._clock),
                occurred_at=format_ts(self._clock.now()),
                actor_user_id=actor.user_id if actor else None,
                actor_ip=client_ip,
                action=event.action,
                target_type=event.target_type,
                target_id=event.target_id,
                detail=audit_detail(event.detail),
            )
        )
