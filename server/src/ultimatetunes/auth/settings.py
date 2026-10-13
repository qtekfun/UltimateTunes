# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings of the auth area (`UT_*` env vars, secrets also as Docker secrets). Owner: PLAN T04.

- `UT_BOOTSTRAP_ADMIN_USERNAME` + `UT_BOOTSTRAP_ADMIN_PASSWORD`: create the first admin when the
  api starts on an empty `users` table (or with `ultimatetunes bootstrap-admin`). There is never
  a default password: without both variables nothing is created.
- Lockout: `UT_AUTH_MAX_FAILURES_PER_IP` / `UT_AUTH_MAX_FAILURES_PER_USER` failed attempts lock
  the IP / username for `UT_AUTH_LOCKOUT_S` seconds. The username lock applies to checks from
  the admin's networks only; from outside, each consecutive failure of a username delays its
  next check by `UT_AUTH_OUTSIDE_BACKOFF_BASE_S` (1), doubling up to
  `UT_AUTH_OUTSIDE_BACKOFF_MAX_S` (300), reset by a success (auth/service.py).
- Rate limits: `UT_AUTH_KEY_RATE_PER_S` / `UT_AUTH_KEY_BURST` per API key on every request;
  `UT_AUTH_LOGIN_RATE_PER_S` / `UT_AUTH_LOGIN_BURST` per IP on password checks.
- Brakes (auth/throttle.py): `UT_AUTH_ARGON2_CONCURRENCY` password verifications at once,
  waiting at most `UT_AUTH_ARGON2_WAIT_S` for a slot; `UT_AUTH_MAX_FAILURES_GLOBAL_PER_MIN`
  failures per minute from outside lock unknown keys, and outside password checks of
  usernames that failed recently, for `UT_AUTH_GLOBAL_LOCKOUT_S`. IPv6 clients are counted by
  their /64.
"""

from typing import Literal

from pydantic import Field, SecretStr

from ultimatetunes.settings import AreaSettings

# Who must use a second factor once the server operator turns the policy on. `off`: nobody is
# forced (a user may still enable TOTP for themselves); `admins`: every admin; `all`: everyone.
Require2fa = Literal["off", "admins", "all"]


class AuthSettings(AreaSettings):
    bootstrap_admin_username: str | None = None
    bootstrap_admin_password: SecretStr | None = None
    # Optional TOTP second factor on the password logins (admin panel, web player,
    # POST /ut/v1/keys). API-key auth is never a second factor (the app keeps working).
    auth_require_2fa: Require2fa = "off"
    auth_2fa_window: int = Field(default=1, ge=0, le=10)
    auth_max_failures_per_ip: int = Field(default=10, ge=1)
    auth_max_failures_per_user: int = Field(default=5, ge=1)
    auth_lockout_s: int = Field(default=900, ge=1)
    auth_outside_backoff_base_s: float = Field(default=1.0, gt=0, le=60)
    auth_outside_backoff_max_s: float = Field(default=300.0, gt=0, le=3600)
    auth_key_rate_per_s: float = Field(default=50.0, gt=0)
    auth_key_burst: float = Field(default=200.0, gt=0)
    auth_login_rate_per_s: float = Field(default=0.2, gt=0)
    auth_login_burst: float = Field(default=5.0, gt=0)
    auth_argon2_concurrency: int = Field(default=2, ge=1, le=16)
    auth_argon2_wait_s: float = Field(default=2.0, ge=0, le=30)
    auth_max_failures_global_per_min: int = Field(default=100, ge=1)
    auth_global_lockout_s: int = Field(default=60, ge=1)
