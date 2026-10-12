# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Argon2id hashing and the password policy."""

import pytest
from argon2 import PasswordHasher, Type

from tests.auth.conftest import fast_passwords
from ultimatetunes.auth.passwords import (
    MAX_LENGTH,
    MIN_LENGTH,
    Passwords,
    check_policy,
    default_hasher,
)
from ultimatetunes.errors import InvalidParameter


def test_hash_is_argon2id_and_verifies() -> None:
    passwords = fast_passwords()
    stored = passwords.hash("correct horse battery staple")
    assert stored.startswith("$argon2id$")
    assert "correct horse" not in stored
    assert passwords.verify(stored, "correct horse battery staple")
    assert not passwords.verify(stored, "correct horse battery stapl")
    assert not passwords.verify("not a hash", "anything")


def test_default_parameters_are_argon2id_owasp() -> None:
    hasher = default_hasher()
    assert hasher.type is Type.ID
    assert (hasher.time_cost, hasher.memory_cost, hasher.parallelism) == (2, 19 * 1024, 1)
    assert Passwords().needs_rehash(fast_passwords().hash("x"))


def test_needs_rehash_when_parameters_change() -> None:
    weak = fast_passwords().hash("correct horse battery staple")
    stronger = Passwords(PasswordHasher(time_cost=2, memory_cost=16, parallelism=1))
    assert stronger.needs_rehash(weak)
    assert not fast_passwords().needs_rehash(weak)


def test_burn_hashes_the_dummy_once(monkeypatch: pytest.MonkeyPatch) -> None:
    passwords = fast_passwords()
    hashed: list[str] = []
    original = passwords.hash

    def spy(password: str) -> str:
        hashed.append(password)
        return original(password)

    monkeypatch.setattr(passwords, "hash", spy)
    passwords.burn("x")
    passwords.burn("y")
    assert hashed == []  # the dummy goes through the hasher directly, once
    assert passwords._dummy is not None
    assert passwords._dummy.startswith("$argon2id$")
    assert not passwords.verify(passwords._dummy, "x")


def test_policy() -> None:
    check_policy("a" * MIN_LENGTH)
    check_policy("a" * MAX_LENGTH)
    for bad in ("", "a" * (MIN_LENGTH - 1), "a" * (MAX_LENGTH + 1)):
        with pytest.raises(InvalidParameter):
            check_policy(bad)
