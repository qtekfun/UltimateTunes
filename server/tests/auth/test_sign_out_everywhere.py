# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`AuthService.sign_out_everywhere`: every key revoked, every admin and web session ended
(audit I4), only for the user itself or an admin."""

import json

import pytest

from tests.auth.conftest import IP, Account
from ultimatetunes.admin.routes import SESSION_EPOCH_KEY
from ultimatetunes.auth.repository import AuditEntry, SessionEpochRepository
from ultimatetunes.auth.service import SESSION_EPOCH_PREFIXES, AuthService
from ultimatetunes.core.authn import Principal
from ultimatetunes.core.clock import FakeClock, format_ts
from ultimatetunes.db import Database
from ultimatetunes.errors import Forbidden, InvalidApiKey, NotFound
from ultimatetunes.web.security import EPOCH_KEY

UNKNOWN_USER = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01ffff"


def epochs(db: Database, user_id: str) -> list[int]:
    with db.read() as conn:
        repo = SessionEpochRepository(conn)
        return [repo.get(prefix + user_id) for prefix in SESSION_EPOCH_PREFIXES]


def signed_out(service: AuthService) -> list[AuditEntry]:
    return [e for e in service.recent_audit() if e.action == "user.sign_out_all"]


def me(account: Account, role: str) -> Principal:
    return Principal(account.user_id, account.username, "admin" if role == "admin" else "user")


def test_the_epochs_are_the_ones_the_panel_and_the_player_read() -> None:
    assert set(SESSION_EPOCH_PREFIXES) == {SESSION_EPOCH_KEY, EPOCH_KEY}


def test_own_account(service: AuthService, db: Database, user: Account, admin: Account) -> None:
    second = service.create_key(user.user_id, "bob laptop", actor=None)
    assert epochs(db, user.user_id) == [0, 0]
    revoked = service.sign_out_everywhere(user.user_id, actor=me(user, "user"), client_ip=IP)
    assert revoked == 2
    assert all(k.revoked_at is not None for k in service.list_keys(user.user_id))
    for secret in (user.key, second.secret):
        with pytest.raises(InvalidApiKey):
            service.authenticate_api_key(secret, None, IP)
    assert epochs(db, user.user_id) == [1, 1]
    # Nobody else is touched.
    assert service.authenticate_api_key(admin.key, None, IP).user_id == admin.user_id
    assert epochs(db, admin.user_id) == [0, 0]
    [entry] = signed_out(service)
    assert (entry.actor_user_id, entry.actor_ip, entry.target_id) == (
        user.user_id,
        IP,
        user.user_id,
    )
    assert json.loads(entry.detail or "") == {"keys": 2}
    # Again: nothing left to revoke, the epochs still move on.
    assert service.sign_out_everywhere(user.user_id, actor=me(user, "user")) == 0
    assert epochs(db, user.user_id) == [2, 2]


def test_a_user_cannot_sign_out_someone_else(
    service: AuthService, db: Database, user: Account, admin: Account
) -> None:
    with pytest.raises(Forbidden):
        service.sign_out_everywhere(admin.user_id, actor=me(user, "user"), client_ip=IP)
    assert service.authenticate_api_key(admin.key, None, IP).user_id == admin.user_id
    assert epochs(db, admin.user_id) == [0, 0]
    assert signed_out(service) == []


def test_an_admin_signs_out_any_user(
    service: AuthService, db: Database, user: Account, admin: Account
) -> None:
    assert service.sign_out_everywhere(user.user_id, actor=me(admin, "admin")) == 1
    assert epochs(db, user.user_id) == [1, 1]
    assert [e.actor_user_id for e in signed_out(service)] == [admin.user_id]
    with pytest.raises(NotFound):
        service.sign_out_everywhere(UNKNOWN_USER, actor=me(admin, "admin"))


def test_a_garbled_epoch_counts_as_zero(
    service: AuthService, db: Database, user: Account, clock: FakeClock
) -> None:
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, 'x', ?)",
            (EPOCH_KEY + user.user_id, format_ts(clock.now())),
        )
    service.sign_out_everywhere(user.user_id, actor=me(user, "user"))
    assert epochs(db, user.user_id) == [1, 1]
