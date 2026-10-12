# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""API key format (contracts/ids.md) and the OpenSubsonic `p` decoding."""

import hashlib

from ultimatetunes.auth import keys
from ultimatetunes.logging import redact

EXAMPLE = "utk_EXAMPLEexampleEXAMPLEexampleEXAMPLEexampleE"


def test_generated_keys_have_the_contract_format_and_are_unique() -> None:
    generated = {keys.generate() for _ in range(200)}
    assert len(generated) == 200
    for key in generated:
        assert keys.is_well_formed(key)
        assert len(key) == 47
        # The log redactor recognises every key we hand out.
        assert key not in redact(f"loose {key} text")


def test_well_formed() -> None:
    assert keys.is_well_formed(EXAMPLE)
    assert not keys.is_well_formed(EXAMPLE[:-1])
    assert not keys.is_well_formed(EXAMPLE + "x")
    assert not keys.is_well_formed("utk_" + "!" * 43)
    assert not keys.is_well_formed("xtk_" + "a" * 43)
    assert not keys.is_well_formed("")


def test_digest_and_prefix() -> None:
    assert keys.digest(EXAMPLE) == hashlib.sha256(EXAMPLE.encode()).hexdigest()
    assert len(keys.digest(EXAMPLE)) == 64
    assert keys.prefix(EXAMPLE) == "utk_EXAMPLEe"


def test_decode_password() -> None:
    assert keys.decode_password(EXAMPLE) == EXAMPLE
    assert keys.decode_password("enc:" + EXAMPLE.encode().hex()) == EXAMPLE
    assert keys.decode_password("enc:" + "ñ".encode().hex().upper()) == "ñ"
    assert keys.decode_password("enc:zz") is None
    assert keys.decode_password("enc:ff") is None  # not UTF-8
