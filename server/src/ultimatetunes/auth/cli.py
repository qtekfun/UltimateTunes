# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Commands of the auth area (`commands.AREAS`). Owner: PLAN T04.

`ultimatetunes bootstrap-admin [USERNAME]` creates the first admin, once: it refuses when any
user exists. The username comes from the argument or `UT_BOOTSTRAP_ADMIN_USERNAME`; the password
from `UT_BOOTSTRAP_ADMIN_PASSWORD` (env var or Docker secret), else it is asked on the terminal
(twice, not echoed) or read as the first line of standard input. There is no default password,
and the password is never printed or logged. Run `ultimatetunes migrate` first.
"""

import getpass
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TextIO

from ultimatetunes.commands import CommandRegistry
from ultimatetunes.settings import Settings


@dataclass
class Terminal:
    """Where the command talks (replaced in tests)."""

    stdin: TextIO = field(default_factory=lambda: sys.stdin)
    stdout: TextIO = field(default_factory=lambda: sys.stdout)
    stderr: TextIO = field(default_factory=lambda: sys.stderr)
    ask: Callable[[str], str] = getpass.getpass


def read_password(term: Terminal) -> str:
    if term.stdin.isatty():
        first = term.ask("Password for the admin: ")
        if term.ask("Repeat the password: ") != first:
            raise ValueError("The passwords do not match")
        return first
    return term.stdin.readline().rstrip("\r\n")


def run_bootstrap_admin(
    settings: Settings, args: Sequence[str], term: Terminal | None = None
) -> int:
    # Heavy imports inside the command (commands.py): every command module is imported for --help.
    from ultimatetunes.auth.service import AuthService  # noqa: PLC0415
    from ultimatetunes.auth.settings import AuthSettings  # noqa: PLC0415
    from ultimatetunes.core.clock import SystemClock  # noqa: PLC0415
    from ultimatetunes.core.ratelimit import SqliteRateLimiter  # noqa: PLC0415
    from ultimatetunes.db.database import Database  # noqa: PLC0415
    from ultimatetunes.db.driver import DatabaseError  # noqa: PLC0415
    from ultimatetunes.errors import TunesError  # noqa: PLC0415

    term = term or Terminal()
    stdout, stderr = term.stdout, term.stderr
    auth_settings = AuthSettings()
    if len(args) > 1:
        raise SystemExit("usage: ultimatetunes bootstrap-admin [USERNAME]")
    username = args[0] if args else auth_settings.bootstrap_admin_username
    if not username:
        stderr.write("bootstrap-admin: give a username (argument or UT_BOOTSTRAP_ADMIN_USERNAME)\n")
        return 2
    secret = auth_settings.bootstrap_admin_password
    try:
        password = secret.get_secret_value() if secret is not None else read_password(term)
    except ValueError as exc:
        stderr.write(f"bootstrap-admin: {exc}\n")
        return 1
    clock = SystemClock()
    db = Database.sqlite(settings.database_file)
    try:
        service = AuthService(db, clock, SqliteRateLimiter(db, clock), auth_settings)
        created = service.bootstrap_admin(username, password)
    except TunesError as exc:
        stderr.write(f"bootstrap-admin: {exc.message}\n")
        return 1
    except DatabaseError:
        stderr.write("bootstrap-admin: the database is not ready, run `ultimatetunes migrate`\n")
        return 1
    finally:
        db.close()
    if not created:
        stderr.write("bootstrap-admin: users already exist, nothing was changed\n")
        return 1
    stdout.write(f"bootstrap-admin: admin {username.strip().lower()} created\n")
    return 0


def register(registry: CommandRegistry) -> None:
    registry.add(
        "bootstrap-admin",
        run_bootstrap_admin,
        help="Create the first admin account (once; password from env or stdin)",
    )
