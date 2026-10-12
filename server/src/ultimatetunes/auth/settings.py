# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings of the auth area (`UT_*` env vars, secrets also as Docker secrets). Owner: PLAN T04.

- `UT_BOOTSTRAP_ADMIN_USERNAME` + `UT_BOOTSTRAP_ADMIN_PASSWORD`: create the first admin when the
  api starts on an empty `users` table (or with `ultimatetunes bootstrap-admin`). There is never
  a default password: without both variables nothing is created.
- Lockout: `UT_AUTH_MAX_FAILURES_PER_IP` / `UT_AUTH_MAX_FAILURES_PER_USER` failed attempts lock
  the IP / username for `UT_AUTH_LOCKOUT_S` seconds.
- Rate limits: `UT_AUTH_KEY_RATE_PER_S` / `UT_AUTH_KEY_BURST` per API key on every request;
  `UT_AUTH_LOGIN_RATE_PER_S` / `UT_AUTH_LOGIN_BURST` per IP on password checks.
"""

from pydantic import Field, SecretStr

from ultimatetunes.settings import AreaSettings


class AuthSettings(AreaSettings):
    bootstrap_admin_username: str | None = None
    bootstrap_admin_password: SecretStr | None = None
    auth_max_failures_per_ip: int = Field(default=10, ge=1)
    auth_max_failures_per_user: int = Field(default=5, ge=1)
    auth_lockout_s: int = Field(default=900, ge=1)
    auth_key_rate_per_s: float = Field(default=50.0, gt=0)
    auth_key_burst: float = Field(default=200.0, gt=0)
    auth_login_rate_per_s: float = Field(default=0.2, gt=0)
    auth_login_burst: float = Field(default=5.0, gt=0)
