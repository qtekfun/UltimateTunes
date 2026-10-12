# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The command registry: each area registers its own commands."""

from collections.abc import Sequence

import pytest

from ultimatetunes.commands import AREAS, CommandRegistry, build_registry, no_args
from ultimatetunes.settings import Settings


def test_every_area_registers_its_commands() -> None:
    specs = build_registry().specs()
    names = [spec.name for spec in specs]
    # The core set is always there; areas (e.g. auth's bootstrap-admin) add their own without
    # editing this test.
    assert {"api", "migrate", "worker"} <= set(names)
    assert names[:2] == ["api", "migrate"]
    assert len(names) == len(set(names))
    assert all(spec.help.strip() for spec in specs)
    assert AREAS[0] == "ultimatetunes.cli"


def test_names_are_checked_and_unique() -> None:
    registry = CommandRegistry()

    def run(_s: Settings, _a: Sequence[str]) -> int:
        return 0

    registry.add("bootstrap-admin", run, help="x")
    with pytest.raises(ValueError, match="twice"):
        registry.add("bootstrap-admin", run, help="x")
    for bad in ("", "Upper", "-x", "a b", "x" * 33):
        with pytest.raises(ValueError, match="invalid"):
            registry.add(bad, run, help="x")
    assert registry.get("bootstrap-admin").help == "x"


def test_no_args_refuses_extra_words(settings: Settings) -> None:
    command = no_args(lambda _s: 7)
    assert command(settings, []) == 7
    with pytest.raises(SystemExit, match="unexpected arguments: a b"):
        command(settings, ["a", "b"])
