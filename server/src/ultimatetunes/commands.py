# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Command registry of the `ultimatetunes` command (one image, several roles and commands).

Owned by the coordinator. Each area registers its own commands in its own module, so parallel
streams never edit a shared file: a module listed in `AREAS` exposes

    def register(registry: CommandRegistry) -> None:
        registry.add("bootstrap-admin", run_bootstrap_admin, help="Create the first admin")

and a command is `run(settings, args) -> exit code`, where `args` are the words after the
command name (the command parses them itself; `no_args` wraps a command that takes none).
Modules import their heavy dependencies inside the command, not at import time, because every
command module is imported to build the parser.
"""

import importlib
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ultimatetunes.settings import Settings

Command = Callable[[Settings, Sequence[str]], int]

# Modules that register commands, in help order. Adding a module here is a coordinator change.
AREAS: tuple[str, ...] = (
    "ultimatetunes.cli",  # api, migrate (coordinator)
    "ultimatetunes.worker.cli",  # worker (PLAN T08)
    "ultimatetunes.auth.cli",  # e.g. bootstrap-admin (PLAN T04)
    "ultimatetunes.canary.cli",  # canary (PLAN T19)
)

_NAME = re.compile(r"^[a-z][a-z0-9-]{0,31}$")


@dataclass(frozen=True)
class CommandSpec:
    name: str
    run: Command
    help: str


class CommandRegistry:
    def __init__(self) -> None:
        self._commands: dict[str, CommandSpec] = {}

    def add(self, name: str, run: Command, *, help: str) -> None:  # noqa: A002 - argparse's word
        if not _NAME.fullmatch(name):
            raise ValueError(f"invalid command name: {name!r}")
        if name in self._commands:
            raise ValueError(f"command {name} registered twice")
        self._commands[name] = CommandSpec(name, run, help)

    def get(self, name: str) -> CommandSpec:
        return self._commands[name]

    def specs(self) -> list[CommandSpec]:
        return list(self._commands.values())


def no_args(run: Callable[[Settings], int]) -> Command:
    """A command that takes no arguments: extra words are a usage error."""

    def command(settings: Settings, args: Sequence[str]) -> int:
        if args:
            raise SystemExit(f"unexpected arguments: {' '.join(args)}")
        return run(settings)

    return command


def build_registry(areas: Sequence[str] = AREAS) -> CommandRegistry:
    registry = CommandRegistry()
    for module in areas:
        importlib.import_module(module).register(registry)
    return registry
