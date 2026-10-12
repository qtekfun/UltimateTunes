# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`docs/configuration.md` documents every `UT_*` setting, with its real default.

The settings are found from the code itself: every subclass of `Settings` and `AreaSettings`
in the package. A new setting, a renamed one or a changed default fails this test until the
reference table is updated. The variables the compose files interpolate (`${UT_...}`) must be
mentioned too.

To print the rows of the settings the document is missing (fill in the container and meaning
by hand): `uv run python -m tests.tools.test_configuration_doc` from `server/`.
"""

import importlib
import pkgutil
import re
import sys
from collections.abc import Iterator
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings

import ultimatetunes
from ultimatetunes.settings import AreaSettings, Settings

REPO = Path(__file__).resolve().parents[3]
DOC = REPO / "docs" / "configuration.md"
COMPOSE_FILES = [
    *sorted((REPO / "server").glob("compose*.yaml")),
    *sorted((REPO / "deploy").rglob("*.y*ml")),
]
_ROW = re.compile(r"^\| `(UT_[A-Z0-9_]+)` \| (.*?) \| (.*?) \| (.*?) \|$", re.M)
_INTERPOLATED = re.compile(r"\$\{(UT_[A-Z0-9_]+)")


def _subclasses(cls: type[BaseSettings]) -> Iterator[type[BaseSettings]]:
    for sub in cls.__subclasses__():
        yield sub
        yield from _subclasses(sub)


def settings_classes() -> list[type[BaseSettings]]:
    """`Settings` and every `AreaSettings` subclass, after importing the whole package."""
    for module in pkgutil.walk_packages(ultimatetunes.__path__, "ultimatetunes."):
        if not module.name.endswith("__main__"):
            importlib.import_module(module.name)
    return [Settings, *sorted(set(_subclasses(AreaSettings)), key=lambda c: c.__module__)]


def default_text(value: object) -> str:
    """How a default is written in the table's second column."""
    if value is None:
        return "(unset)"
    if isinstance(value, SecretStr):  # pragma: no cover - no secret has a default
        return "(secret)"
    if isinstance(value, bool):
        return f"`{str(value).lower()}`"
    if isinstance(value, float):
        return f"`{value:g}`"
    if value == "":
        return "(empty)"
    return f"`{value}`"


def code_settings() -> dict[str, tuple[str, str]]:
    """`UT_NAME` -> (default as written in the doc, class that reads it)."""
    found: dict[str, tuple[str, str]] = {}
    for cls in settings_classes():
        for name, info in cls.model_fields.items():
            env = "UT_" + name.upper()
            assert env not in found, f"{env} is declared twice"
            found[env] = (default_text(info.default), f"{cls.__module__}.{cls.__name__}")
    return found


def doc_rows() -> dict[str, tuple[str, str, str]]:
    rows: dict[str, tuple[str, str, str]] = {}
    for name, default, container, meaning in _ROW.findall(DOC.read_text(encoding="utf-8")):
        assert name not in rows, f"{name} is documented twice"
        rows[name] = (default.strip(), container.strip(), meaning.strip())
    return rows


def test_every_setting_is_documented_with_its_default() -> None:
    code, doc = code_settings(), doc_rows()
    assert len(code) > 100
    missing = sorted(set(code) - set(doc))
    assert not missing, f"undocumented settings (see the module doc to generate rows): {missing}"
    unknown = sorted(set(doc) - set(code))
    assert not unknown, f"documented settings that no longer exist: {unknown}"
    wrong = {name: (doc[name][0], code[name][0]) for name in code if doc[name][0] != code[name][0]}
    assert not wrong, f"defaults that differ (doc, code): {wrong}"
    for name, (_default, container, meaning) in doc.items():
        assert container in ("api", "worker", "api, worker"), (name, container)
        assert len(meaning) > 10, name


def test_compose_variables_are_documented() -> None:
    text = DOC.read_text(encoding="utf-8")
    used = {
        name
        for path in COMPOSE_FILES
        for name in _INTERPOLATED.findall(path.read_text(encoding="utf-8"))
    }
    assert used, "no compose file found"
    missing = sorted(name for name in used if f"`{name}`" not in text)
    assert not missing, f"compose variables missing from docs/configuration.md: {missing}"


def test_default_text() -> None:
    assert default_text(None) == "(unset)"
    assert default_text(True) == "`true`"
    assert default_text(0.25) == "`0.25`"
    assert default_text(600.0) == "`600`"
    assert default_text("") == "(empty)"
    assert default_text(Path("/data")) == "`/data`"
    assert default_text(8) == "`8`"


if __name__ == "__main__":  # pragma: no cover - a helper for whoever adds a setting
    documented = doc_rows()
    for env, (default, owner) in code_settings().items():
        if env not in documented:
            sys.stdout.write(f"| `{env}` | {default} | api | TODO ({owner}) |\n")
