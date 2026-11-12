# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`AuthService.purge_revoked_keys`: revoked keys leave after the retention period, nothing else."""

import asyncio
import json
from contextlib import suppress

import pytest

from tests.auth.conftest import Account
from ultimatetunes.auth.service import AuthService
from ultimatetunes.auth.settings import AuthSettings
from ultimatetunes.auth.web import purge_forever
from ultimatetunes.core.authn import Principal
from ultimatetunes.core.clock import FakeClock

DAY_S = 24 * 3600


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def me(account: Account) -> Principal:
    return Principal(account.user_id, account.username, "user")


def test_the_default_period_is_thirty_days() -> None:
    assert AuthSettings().auth_revoked_key_retention_days == 30


def test_only_old_revoked_keys_go(service: AuthService, clock: FakeClock, user: Account) -> None:
    old = service.create_key(user.user_id, "old phone", actor=None)
    recent = service.create_key(user.user_id, "recent phone", actor=None)
    service.revoke_key(old.key.id, actor=me(user))
    clock.advance(20 * DAY_S)
    service.revoke_key(recent.key.id, actor=me(user))
    clock.advance(11 * DAY_S)  # `old` was revoked 31 days ago, `recent` 11
    assert service.purge_revoked_keys() == 1
    ids = {k.id for k in service.list_keys(user.user_id)}
    assert old.key.id not in ids
    assert {recent.key.id}.issubset(ids)
    # The live key of the fixture stays.
    assert len(ids) == 2
    [entry] = [e for e in service.recent_audit() if e.action == "key.purge"]
    assert json.loads(entry.detail or "") == {"keys": 1}


def test_nothing_to_do_is_quiet_and_idempotent(
    service: AuthService, clock: FakeClock, user: Account
) -> None:
    service.revoke_key(service.list_keys(user.user_id)[0].id, actor=me(user))
    clock.advance(10 * DAY_S)
    assert service.purge_revoked_keys() == 0
    clock.advance(30 * DAY_S)
    assert service.purge_revoked_keys() == 1
    assert service.purge_revoked_keys() == 0
    assert len([e for e in service.recent_audit() if e.action == "key.purge"]) == 1


def test_the_period_is_configurable(
    service: AuthService, clock: FakeClock, user: Account, auth_settings: AuthSettings
) -> None:
    service._settings = auth_settings.model_copy(update={"auth_revoked_key_retention_days": 2})
    service.revoke_key(service.list_keys(user.user_id)[0].id, actor=me(user))
    clock.advance(3 * DAY_S)
    assert service.purge_revoked_keys() == 1


def test_the_retention_must_be_at_least_a_day() -> None:
    with pytest.raises(ValueError):  # noqa: PT011 - pydantic's validation error
        AuthSettings(auth_revoked_key_retention_days=0)


@pytest.mark.anyio
async def test_the_background_task_purges_and_survives_errors() -> None:
    calls: list[int] = []

    class Failing:
        def purge_revoked_keys(self) -> int:
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("database busy")
            return 0

    task = asyncio.ensure_future(purge_forever(Failing(), 0.01))  # type: ignore[arg-type]
    for _ in range(100):
        if len(calls) >= 2:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    assert len(calls) >= 2
