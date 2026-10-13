# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings of the YouTube cookies feature (`UT_*` env vars, Docker secrets). Owner: D14.

`UT_YTDLP_COOKIES_KEY` seals the stored cookies at rest (a urlsafe-base64 32-byte Fernet key,
its own key, never the TOTP one). Without it the store fails closed: setting or using cookies
raises `FeatureDisabled`, never a plaintext fallback (`auth/secretbox.py`, SECURITY.md).
"""

from pydantic import Field, SecretStr, field_validator

from ultimatetunes.settings import AreaSettings


class YouTubeSettings(AreaSettings):
    # Fernet key that seals the YouTube cookies at rest, from an env var or the Docker secret
    # `ut_ytdlp_cookies_key`. Unset: the cookies store is disabled and fails closed.
    ytdlp_cookies_key: SecretStr | None = None
    # Largest cookies.txt the endpoint accepts (bytes); a real one is a few KiB.
    ytdlp_cookies_max_bytes: int = Field(default=256 * 1024, ge=1024, le=4 * 1024 * 1024)

    @field_validator("ytdlp_cookies_key")
    @classmethod
    def _valid_fernet_key(cls, value: SecretStr | None) -> SecretStr | None:
        """A blank key is unset; otherwise it must be a valid Fernet key, checked at start so a
        malformed one is refused before any cookies request. The value is never echoed
        (`hide_input_in_errors`)."""
        if value is None or not value.get_secret_value().strip():
            return None
        from cryptography.fernet import Fernet  # noqa: PLC0415

        try:
            Fernet(value.get_secret_value().encode("ascii"))
        except (ValueError, TypeError) as exc:
            raise ValueError(
                "UT_YTDLP_COOKIES_KEY must be a urlsafe-base64 32-byte Fernet key"
            ) from exc
        return value
