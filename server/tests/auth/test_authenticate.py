# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Every authentication rule of `/rest` and `/ut/v1` (SPEC RF-02, contracts/errors.md)."""

import pytest

from tests.auth.conftest import IP, Account
from ultimatetunes.auth import keys
from ultimatetunes.auth.service import HELP_URL, AuthService
from ultimatetunes.core.clock import FakeClock, format_ts
from ultimatetunes.db import Database
from ultimatetunes.errors import (
    AccountDisabled,
    AuthenticationFailed,
    AuthenticationRequired,
    ConflictingAuth,
    InvalidApiKey,
    RateLimited,
    TokenAuthNotSupported,
    spec_for,
)

UNKNOWN_KEY = "utk_EXAMPLEexampleEXAMPLEexampleEXAMPLEexampleE"


def params(**values: str) -> dict[str, list[str]]:
    return {name: [value] for name, value in values.items()}


def key_row(db: Database, key_id: str) -> dict[str, object]:
    with db.read() as conn:
        row = conn.execute(
            "SELECT last_used_at, last_used_ip, revoked_at FROM api_keys WHERE id = ?", (key_id,)
        ).fetchone()
    assert row is not None
    return dict(row)


# ---------------------------------------------------------------- /rest: apiKey


def test_api_key_alone(service: AuthService, admin: Account) -> None:
    principal = service.authenticate_subsonic(params(apiKey=admin.key, f="json"), IP)
    assert principal.user_id == admin.user_id
    assert principal.username == "alice"
    assert principal.role == "admin"
    assert principal.is_admin
    assert principal.api_key_id == admin.key_id


@pytest.mark.parametrize("other", ["u", "p", "t", "s"])
def test_api_key_with_any_other_credential_is_error_43(
    service: AuthService, admin: Account, other: str
) -> None:
    with pytest.raises(ConflictingAuth) as caught:
        service.authenticate_subsonic(params(apiKey=admin.key, **{other: "alice"}), IP)
    assert spec_for(caught.value).subsonic_code == 43


@pytest.mark.parametrize("key", ["utk_x", UNKNOWN_KEY, "", "enc:00"])
def test_unknown_or_malformed_key_is_error_44(
    service: AuthService, admin: Account, key: str
) -> None:
    if not key:
        # An empty apiKey counts as absent: no credentials at all.
        with pytest.raises(AuthenticationRequired):
            service.authenticate_subsonic(params(apiKey=key), IP)
        return
    with pytest.raises(InvalidApiKey) as caught:
        service.authenticate_subsonic(params(apiKey=key), IP)
    assert spec_for(caught.value).subsonic_code == 44
    assert caught.value.help_url == HELP_URL


def test_revoked_key_is_error_44(service: AuthService, admin: Account) -> None:
    service.revoke_key(admin.key_id, actor=None)
    with pytest.raises(InvalidApiKey):
        service.authenticate_subsonic(params(apiKey=admin.key), IP)


def test_key_of_a_disabled_user_is_error_50(
    service: AuthService, admin: Account, user: Account
) -> None:
    service.set_disabled(user.user_id, True, actor=None)
    with pytest.raises(AccountDisabled) as caught:
        service.authenticate_subsonic(params(apiKey=user.key), IP)
    assert spec_for(caught.value).subsonic_code == 50
    with pytest.raises(AccountDisabled):
        service.authenticate_subsonic(params(u="bob", p=user.key), IP)
    service.set_disabled(user.user_id, False, actor=None)
    assert service.authenticate_subsonic(params(apiKey=user.key), IP).user_id == user.user_id


# ---------------------------------------------------------------- /rest: token auth


@pytest.mark.parametrize(
    "creds",
    [
        {"u": "alice", "t": "26719a1196d2a940705a59634eb18eab", "s": "c19b2d"},
        {"t": "26719a1196d2a940705a59634eb18eab"},
        {"s": "c19b2d"},
        {"u": "alice", "p": "x", "t": "abc", "s": "def"},
    ],
)
def test_token_auth_is_error_42(
    service: AuthService, admin: Account, creds: dict[str, str]
) -> None:
    with pytest.raises(TokenAuthNotSupported) as caught:
        service.authenticate_subsonic(params(**creds), IP)
    assert spec_for(caught.value).subsonic_code == 42
    assert caught.value.help_url == HELP_URL


# ---------------------------------------------------------------- /rest: key as password


def test_key_as_password_in_clear_and_enc(service: AuthService, admin: Account) -> None:
    clear = service.authenticate_subsonic(params(u="alice", p=admin.key), IP)
    assert clear.user_id == admin.user_id
    assert clear.api_key_id == admin.key_id
    encoded = "enc:" + admin.key.encode().hex()
    assert service.authenticate_subsonic(params(u="ALICE", p=encoded), IP) == clear


@pytest.mark.parametrize(
    "password",
    [
        "correct horse battery staple",  # the account password is never accepted on /rest
        UNKNOWN_KEY,
        "enc:zz",
        "enc:" + UNKNOWN_KEY.encode().hex(),
    ],
)
def test_wrong_key_as_password_is_error_40(
    service: AuthService, admin: Account, password: str
) -> None:
    with pytest.raises(AuthenticationFailed) as caught:
        service.authenticate_subsonic(params(u="alice", p=password), IP)
    assert spec_for(caught.value).subsonic_code == 40


def test_key_of_another_user_as_password_is_error_40(
    service: AuthService, admin: Account, user: Account
) -> None:
    with pytest.raises(AuthenticationFailed):
        service.authenticate_subsonic(params(u="alice", p=user.key), IP)
    with pytest.raises(AuthenticationFailed):
        service.authenticate_subsonic(params(u="nobody", p=user.key), IP)


def test_revoked_key_as_password_is_error_40(service: AuthService, admin: Account) -> None:
    service.revoke_key(admin.key_id, actor=None)
    with pytest.raises(AuthenticationFailed):
        service.authenticate_subsonic(params(u="alice", p=admin.key), IP)


@pytest.mark.parametrize("creds", [{}, {"u": "alice"}, {"p": "x"}, {"u": "", "p": ""}])
def test_missing_credentials_are_error_10(service: AuthService, creds: dict[str, str]) -> None:
    with pytest.raises(AuthenticationRequired) as caught:
        service.authenticate_subsonic(params(**creds), IP)
    assert spec_for(caught.value).subsonic_code == 10


# ---------------------------------------------------------------- /ut/v1


def test_ut_header_or_query_key(service: AuthService, admin: Account) -> None:
    assert service.authenticate_api_key(admin.key, None, IP).user_id == admin.user_id
    assert service.authenticate_api_key(None, admin.key, IP).user_id == admin.user_id
    assert service.authenticate_api_key(admin.key, admin.key, IP).user_id == admin.user_id


def test_ut_conflicting_and_missing_and_invalid(service: AuthService, admin: Account) -> None:
    with pytest.raises(ConflictingAuth):
        service.authenticate_api_key(admin.key, UNKNOWN_KEY, IP)
    with pytest.raises(AuthenticationRequired):
        service.authenticate_api_key(None, None, IP)
    with pytest.raises(AuthenticationRequired):
        service.authenticate_api_key("", "", IP)
    with pytest.raises(InvalidApiKey) as caught:
        service.authenticate_api_key(UNKNOWN_KEY, None, IP)
    assert caught.value.help_url is None


# ---------------------------------------------------------------- last use


def test_last_use_is_written_at_most_once_a_minute_per_ip(
    service: AuthService, db: Database, clock: FakeClock, admin: Account
) -> None:
    start = format_ts(clock.now())
    service.authenticate_api_key(admin.key, None, IP)
    assert key_row(db, admin.key_id) == {
        "last_used_at": start,
        "last_used_ip": IP,
        "revoked_at": None,
    }
    clock.advance(30)
    service.authenticate_api_key(admin.key, None, IP)
    assert key_row(db, admin.key_id)["last_used_at"] == start
    service.authenticate_api_key(admin.key, None, "198.51.100.7")
    assert key_row(db, admin.key_id)["last_used_ip"] == "198.51.100.7"
    assert key_row(db, admin.key_id)["last_used_at"] == format_ts(clock.now())
    clock.advance(60)
    service.authenticate_api_key(admin.key, None, "198.51.100.7")
    assert key_row(db, admin.key_id)["last_used_at"] == format_ts(clock.now())


def test_listing_shows_last_use(service: AuthService, admin: Account) -> None:
    service.authenticate_api_key(admin.key, None, None)
    (listed,) = service.list_keys(admin.user_id)
    assert listed.last_used_at is not None
    assert listed.last_used_ip is None


# ---------------------------------------------------------------- rate limit and lockout


def test_per_key_rate_limit(
    service: AuthService, admin: Account, user: Account, clock: FakeClock
) -> None:
    for _ in range(50):
        service.authenticate_api_key(admin.key, None, IP)
    with pytest.raises(RateLimited) as caught:
        service.authenticate_api_key(admin.key, None, IP)
    assert caught.value.retry_after_s == 1
    # Another key of the same IP is not affected.
    service.authenticate_subsonic(params(apiKey=user.key), IP)
    clock.advance(1)
    service.authenticate_api_key(admin.key, None, IP)


def test_invalid_keys_lock_the_ip(
    service: AuthService, admin: Account, clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    for _ in range(3):
        with pytest.raises(InvalidApiKey):
            service.authenticate_subsonic(params(apiKey=UNKNOWN_KEY), IP)
    # Locked: bad credentials now get 429, whatever the error would have been.
    for creds in (params(apiKey=UNKNOWN_KEY), params(u="alice", p="wrong")):
        with pytest.raises(RateLimited) as caught:
            service.authenticate_subsonic(creds, IP)
        assert caught.value.retry_after_s == 60
    with pytest.raises(RateLimited):
        service.authenticate_api_key(UNKNOWN_KEY, None, IP)
    # A valid key from the same (shared) IP still works.
    assert service.authenticate_subsonic(params(apiKey=admin.key), IP).user_id == admin.user_id
    # Other IPs are not affected.
    with pytest.raises(InvalidApiKey):
        service.authenticate_subsonic(params(apiKey=UNKNOWN_KEY), "198.51.100.7")
    assert "auth lockout of ip 192.0.2.10 for 60 s" in caplog.text
    (entry,) = [e for e in service.recent_audit() if e.action == "auth.lockout"]
    assert (entry.target_type, entry.target_id, entry.actor_ip) == ("ip", IP, IP)
    clock.advance(60)
    with pytest.raises(InvalidApiKey):
        service.authenticate_subsonic(params(apiKey=UNKNOWN_KEY), IP)


def test_stale_devices_never_lock_out_their_ip(
    service: AuthService, admin: Account, user: Account
) -> None:
    """A disabled user's device (or one with a revoked key) polling all day is not guessing."""
    service.set_disabled(user.user_id, True, actor=None)
    for _ in range(50):
        with pytest.raises(AccountDisabled):
            service.authenticate_subsonic(params(apiKey=user.key), IP)
    revoked = service.create_key(admin.user_id, "Old tablet", actor=None)
    service.revoke_key(revoked.key.id, actor=None)
    for _ in range(50):
        with pytest.raises(InvalidApiKey):
            service.authenticate_api_key(revoked.secret, None, IP)
    # The household IP is not locked: an unknown key still gets 44, not 429.
    with pytest.raises(InvalidApiKey):
        service.authenticate_subsonic(params(apiKey=UNKNOWN_KEY), IP)
    assert [e for e in service.recent_audit() if e.action == "auth.lockout"] == []


def test_stale_devices_get_429_while_the_ip_is_locked(
    service: AuthService, admin: Account, user: Account
) -> None:
    for _ in range(3):
        with pytest.raises(InvalidApiKey):
            service.authenticate_subsonic(params(apiKey=UNKNOWN_KEY), None)
    service.set_disabled(user.user_id, True, actor=None)
    with pytest.raises(RateLimited):
        service.authenticate_subsonic(params(apiKey=user.key), None)
    service.revoke_key(admin.key_id, actor=None)
    with pytest.raises(RateLimited):
        service.authenticate_api_key(admin.key, None, None)
    (entry,) = [e for e in service.recent_audit() if e.action == "auth.lockout"]
    assert entry.target_id == "unknown"


def test_no_key_ever_matches_by_prefix_or_hash(service: AuthService, admin: Account) -> None:
    last = "B" if admin.key.endswith("A") else "A"
    for wrong in (keys.prefix(admin.key), keys.digest(admin.key), admin.key[:-1] + last):
        with pytest.raises(InvalidApiKey):
            service.authenticate_api_key(wrong, None, "203.0.113.1")
