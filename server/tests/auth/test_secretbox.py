# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Encrypting the TOTP secret at rest, and failing closed without a key (auth/secretbox.py)."""

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from ultimatetunes.auth.secretbox import InvalidToken, SecretBox
from ultimatetunes.errors import FeatureDisabled


def _box() -> SecretBox:
    return SecretBox(SecretStr(Fernet.generate_key().decode("ascii")))


def test_round_trip_recovers_the_plaintext() -> None:
    box = _box()
    sealed = box.encrypt("JBSWY3DPEHPK3PXP")
    assert sealed != "JBSWY3DPEHPK3PXP"
    assert box.decrypt(sealed) == "JBSWY3DPEHPK3PXP"


def test_available_reflects_the_key() -> None:
    assert _box().available
    assert not SecretBox(None).available


def test_encrypt_without_a_key_fails_closed() -> None:
    with pytest.raises(FeatureDisabled):
        SecretBox(None).encrypt("secret")


def test_decrypt_without_a_key_fails_closed() -> None:
    with pytest.raises(FeatureDisabled):
        SecretBox(None).decrypt("whatever")


def test_decrypt_with_a_different_key_is_rejected() -> None:
    sealed = _box().encrypt("JBSWY3DPEHPK3PXP")
    with pytest.raises(InvalidToken):
        _box().decrypt(sealed)
