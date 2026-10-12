# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings of the admin panel (`UT_*` env vars; secrets also as Docker secrets). Owner: T15.

Secrets come from env vars or Docker secrets, never from the database.

- `UT_ADMIN_SESSION_SECRET` (or the Docker secret `admin_session_secret`): key that signs the
  session cookies, at least 32 characters. Every api replica needs the same one. Without it the
  api makes a random key at start (sessions end on every restart) and logs a warning.
- `UT_ADMIN_SESSION_TTL_S`: lifetime of a session (default 8 hours).
- `UT_ADMIN_ALLOWED_NETWORKS`: comma-separated CIDRs allowed to reach `/admin` (default:
  loopback, private LAN ranges, link-local and Tailscale). Anything else gets 403 before any
  other check. `0.0.0.0/0,::/0` opts in to access from anywhere (SPEC §7). The default is safe
  but broad; a deployment narrows it to its tailnet and its LAN's /24, leaving the Docker bridge
  ranges out (deploy/README.md, "Exposing UltimateTunes").
- `UT_ADMIN_PUBLIC_URL`: the server address the app should use, prefilled in the QR form of a
  new key (default: the address the browser used).
- `UT_ADMIN_NOTIFY_INTERVAL_S`: how often failed downloads and canary runs are checked for
  notifications (the target itself is set in the panel).
- `UT_NOTIFY_TOKEN` (or the Docker secret `ut_notify_token`): an ntfy access token, sent as
  `Authorization: Bearer` to the notification target. Or `UT_NOTIFY_USERNAME` +
  `UT_NOTIFY_PASSWORD` (Docker secrets `ut_notify_username`, `ut_notify_password`) for HTTP
  Basic. One or the other, never both. They live only in the environment: the server has no
  encryption library to keep them in its database, so the panel shows whether they are set
  and never takes them.
"""

from typing import Self

from pydantic import Field, SecretStr, field_validator, model_validator

from ultimatetunes.core import netaddr
from ultimatetunes.core.netaddr import IpNetwork
from ultimatetunes.settings import AreaSettings, settings_config

__all__ = ["DEFAULT_ALLOWED_NETWORKS", "AdminSettings", "IpNetwork", "parse_networks"]

# Loopback, RFC 1918, link-local and IPv6 ULA (LAN), and Tailscale (100.64.0.0/10 and its ULA).
DEFAULT_ALLOWED_NETWORKS = (
    "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,169.254.0.0/16,"
    "fc00::/7,fe80::/10,100.64.0.0/10,fd7a:115c:a1e0::/48"
)
MIN_SECRET_LENGTH = 32
MAX_NOTIFY_CREDENTIAL_LENGTH = 512


def parse_networks(text: str) -> tuple[IpNetwork, ...]:
    networks = netaddr.parse_networks(text)
    if not networks:
        raise ValueError("at least one network is needed")
    return networks


class AdminSettings(AreaSettings):
    # A refused value is never echoed in the error (it may be a password or a token).
    model_config = settings_config() | {"hide_input_in_errors": True}

    admin_session_secret: SecretStr | None = None
    admin_session_ttl_s: int = Field(default=8 * 3600, ge=60, le=7 * 24 * 3600)
    admin_allowed_networks: str = DEFAULT_ALLOWED_NETWORKS
    admin_public_url: str | None = None
    admin_notify_interval_s: int = Field(default=60, ge=5, le=3600)
    notify_token: SecretStr | None = None
    notify_username: SecretStr | None = None
    notify_password: SecretStr | None = None

    @field_validator("admin_session_secret")
    @classmethod
    def _long_enough(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and len(value.get_secret_value()) < MIN_SECRET_LENGTH:
            raise ValueError(f"the admin session secret needs {MIN_SECRET_LENGTH}+ characters")
        return value

    @field_validator("notify_token", "notify_username", "notify_password")
    @classmethod
    def _header_safe(cls, value: SecretStr | None) -> SecretStr | None:
        """Blank means unset; otherwise printable text that fits in one header line. The
        value is never echoed in the error."""
        if value is None or not value.get_secret_value().strip():
            return None
        text = value.get_secret_value()
        if len(text) > MAX_NOTIFY_CREDENTIAL_LENGTH or not text.isprintable():
            raise ValueError("notification credentials must be printable and not too long")
        return value

    @model_validator(mode="after")
    def _one_kind_of_credentials(self) -> Self:
        user, password = self.notify_username, self.notify_password
        if (user is None) != (password is None):
            raise ValueError("set both UT_NOTIFY_USERNAME and UT_NOTIFY_PASSWORD, or neither")
        if self.notify_token is not None and user is not None:
            raise ValueError("set UT_NOTIFY_TOKEN or UT_NOTIFY_USERNAME/PASSWORD, not both")
        if user is not None and ":" in user.get_secret_value():
            raise ValueError("UT_NOTIFY_USERNAME must not contain ':'")
        if self.notify_token is not None and any(
            c.isspace() or not c.isascii() for c in self.notify_token.get_secret_value()
        ):
            raise ValueError("UT_NOTIFY_TOKEN must be ASCII without spaces")
        return self

    @field_validator("admin_allowed_networks")
    @classmethod
    def _valid_networks(cls, value: str) -> str:
        parse_networks(value)
        return value

    def networks(self) -> tuple[IpNetwork, ...]:
        return parse_networks(self.admin_allowed_networks)
