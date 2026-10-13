# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`AuthSettings` reads `UT_*` variables; no default bootstrap password exists."""

import pytest
from pydantic import ValidationError

from ultimatetunes.auth.settings import AuthSettings


def test_defaults_have_no_bootstrap_credentials() -> None:
    settings = AuthSettings()
    assert settings.bootstrap_admin_username is None
    assert settings.bootstrap_admin_password is None
    assert settings.auth_max_failures_per_ip == 10
    assert settings.auth_max_failures_per_user == 5
    assert settings.auth_lockout_s == 900


def test_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UT_BOOTSTRAP_ADMIN_USERNAME", "root")
    monkeypatch.setenv("UT_BOOTSTRAP_ADMIN_PASSWORD", "a long secret passphrase")
    settings = AuthSettings()
    assert settings.bootstrap_admin_username == "root"
    assert settings.bootstrap_admin_password is not None
    assert "passphrase" not in repr(settings)
    monkeypatch.setenv("UT_AUTH_LOCKOUT_S", "0")
    with pytest.raises(ValidationError):
        AuthSettings()


def test_valid_totp_key_is_accepted() -> None:
    from cryptography.fernet import Fernet  # noqa: PLC0415
    from pydantic import SecretStr  # noqa: PLC0415

    key = Fernet.generate_key().decode("ascii")
    settings = AuthSettings(totp_encryption_key=SecretStr(key))
    assert settings.totp_encryption_key is not None
    assert settings.totp_encryption_key.get_secret_value() == key


def test_blank_totp_key_is_unset() -> None:
    from pydantic import SecretStr  # noqa: PLC0415

    assert AuthSettings(totp_encryption_key=SecretStr("   ")).totp_encryption_key is None


def test_malformed_totp_key_is_rejected_without_echoing_it() -> None:
    from pydantic import SecretStr  # noqa: PLC0415

    with pytest.raises(ValidationError) as caught:
        AuthSettings(totp_encryption_key=SecretStr("not-a-valid-fernet-key"))
    assert "not-a-valid-fernet-key" not in str(caught.value)
