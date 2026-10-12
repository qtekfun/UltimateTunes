# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Small parameter readers shared by the library's OpenSubsonic routes."""

from typing import TYPE_CHECKING

from ultimatetunes.errors import InvalidParameter

if TYPE_CHECKING:
    from ultimatetunes.subsonic.router import SubsonicRequest

_TRUE = frozenset({"true", "1"})
_FALSE = frozenset({"false", "0"})


def get_bool(req: "SubsonicRequest", name: str, default: bool | None = None) -> bool | None:
    value = req.get(name)
    if value is None or value == "":
        return default
    lowered = value.lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    raise InvalidParameter(f"Parameter {name} must be true or false")
