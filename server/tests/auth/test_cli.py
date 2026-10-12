# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`ultimatetunes bootstrap-admin`: once, never with a default password, never echoing it."""

import io
import sys
from collections.abc import Callable

import pytest

from tests.auth.conftest import fast_passwords
from ultimatetunes.auth import cli
from ultimatetunes.auth.service import AuthService
from ultimatetunes.commands import build_registry
from ultimatetunes.core.clock import FakeClock
from ultimatetunes.core.ratelimit import SqliteRateLimiter
from ultimatetunes.db import Database
from ultimatetunes.settings import Settings

PASSWORD = "the very first admin password"


class TtyInput(io.StringIO):
    def isatty(self) -> bool:
        return True


def terminal(
    stdin: io.StringIO | None = None, ask: Callable[[str], str] | None = None
) -> cli.Terminal:
    def refuse(prompt: str) -> str:
        raise AssertionError("no prompt expected")

    return cli.Terminal(
        stdin=stdin or io.StringIO(""),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
        ask=ask or refuse,
    )


def output(term: cli.Terminal) -> str:
    out, err = term.stdout, term.stderr
    assert isinstance(out, io.StringIO)
    assert isinstance(err, io.StringIO)
    return out.getvalue() + err.getvalue()


def users(settings: Settings) -> list[tuple[str, str]]:
    db = Database.sqlite(settings.database_file)
    clock = FakeClock()
    service = AuthService(db, clock, SqliteRateLimiter(db, clock), passwords=fast_passwords())
    try:
        return [(u.username, u.role) for u in service.list_users()]
    finally:
        db.close()


def test_command_is_registered() -> None:
    spec = build_registry().get("bootstrap-admin")
    assert spec.run is cli.run_bootstrap_admin
    assert "admin" in spec.help


def test_password_from_env(migrated_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UT_BOOTSTRAP_ADMIN_PASSWORD", PASSWORD)
    term = terminal()
    assert cli.run_bootstrap_admin(migrated_settings, ["Root"], term) == 0
    assert users(migrated_settings) == [("root", "admin")]
    assert "admin root created" in output(term)
    assert PASSWORD not in output(term)
    # One time only.
    term = terminal()
    assert cli.run_bootstrap_admin(migrated_settings, ["other"], term) == 1
    assert "users already exist" in output(term)
    assert users(migrated_settings) == [("root", "admin")]


def test_username_from_env_and_password_from_stdin(
    migrated_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UT_BOOTSTRAP_ADMIN_USERNAME", "admin")
    term = terminal(io.StringIO(PASSWORD + "\r\nignored\n"))
    assert cli.run_bootstrap_admin(migrated_settings, [], term) == 0
    assert users(migrated_settings) == [("admin", "admin")]


def test_password_asked_twice_on_a_terminal(migrated_settings: Settings) -> None:
    prompts: list[str] = []

    def ask(prompt: str) -> str:
        prompts.append(prompt)
        return PASSWORD

    assert cli.run_bootstrap_admin(migrated_settings, ["root"], terminal(TtyInput(), ask)) == 0
    assert len(prompts) == 2
    assert users(migrated_settings) == [("root", "admin")]


def test_mismatched_passwords(migrated_settings: Settings) -> None:
    answers = iter([PASSWORD, PASSWORD + "x"])
    term = terminal(TtyInput(), lambda prompt: next(answers))
    assert cli.run_bootstrap_admin(migrated_settings, ["root"], term) == 1
    assert "do not match" in output(term)
    assert users(migrated_settings) == []


def test_weak_password_or_bad_username(migrated_settings: Settings) -> None:
    term = terminal(io.StringIO("short\n"))
    assert cli.run_bootstrap_admin(migrated_settings, ["root"], term) == 1
    assert "12 to 1024" in output(term)
    assert "short" not in output(term).replace("12 to", "")
    term = terminal(io.StringIO(PASSWORD))
    assert cli.run_bootstrap_admin(migrated_settings, ["no spaces"], term) == 1
    assert users(migrated_settings) == []


def test_usage_errors(settings: Settings) -> None:
    term = terminal()
    assert cli.run_bootstrap_admin(settings, [], term) == 2
    assert "give a username" in output(term)
    with pytest.raises(SystemExit):
        cli.run_bootstrap_admin(settings, ["a", "b"], terminal())


def test_database_not_migrated(settings: Settings) -> None:
    term = terminal(io.StringIO(PASSWORD))
    assert cli.run_bootstrap_admin(settings, ["root"], term) == 1
    assert "run `ultimatetunes migrate`" in output(term)


def test_default_terminal_uses_the_process_streams() -> None:
    term = cli.Terminal()
    assert (term.stdin, term.stdout, term.stderr) == (sys.stdin, sys.stdout, sys.stderr)


def test_default_terminal_in_the_command(
    migrated_settings: Settings, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("UT_BOOTSTRAP_ADMIN_PASSWORD", PASSWORD)
    assert cli.run_bootstrap_admin(migrated_settings, ["root"]) == 0
    captured = capsys.readouterr()
    assert "admin root created" in captured.out
    assert PASSWORD not in captured.out + captured.err
