# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Base for per-area repositories: portable SQL in, typed frozen dataclasses out.

A repository wraps one `Connection` handed out by `Database.transaction()` or `Database.read()`,
so several repositories can share one transaction. Each stream writes its own repositories in
its own package (e.g. `library/repository.py`), on top of this class:

    @dataclass(frozen=True)
    class Track:
        id: str
        title: str
        needs_review: bool

    class TrackRepository(Repository):
        def get(self, track_id: str) -> Track | None:
            return self.one(Track, "SELECT id, title, needs_review FROM tracks WHERE id = ?",
                            (track_id,))

Rules: `?` placeholders only, the portable subset of contracts/db/README.md, timestamps from the
injected clock via `core.clock.format_ts`, booleans as 0/1 (mapped back to `bool` here).
"""

import dataclasses
import types
import typing
from typing import Any, Union, get_args, get_origin, get_type_hints

from ultimatetunes.db.driver import Connection, Params, Row

_HINTS: dict[type, dict[str, Any]] = {}


def _is_bool(hint: Any) -> bool:
    if hint is bool:
        return True
    if get_origin(hint) in (Union, types.UnionType):
        return bool in get_args(hint)
    return False


def from_row[T](cls: type[T], row: Row) -> T:
    """Builds the dataclass `cls` from a row, by column name. Extra columns are an error (keep
    the SELECT and the dataclass in step); `bool` fields accept the 0/1 the database stores."""
    if not dataclasses.is_dataclass(cls):
        raise TypeError(f"{cls.__name__} is not a dataclass")
    hints = _HINTS.get(cls)
    if hints is None:
        hints = get_type_hints(cls)
        _HINTS[cls] = hints
    fields = {f.name for f in dataclasses.fields(cls)}
    unknown = set(row) - fields
    if unknown:
        raise ValueError(f"columns not in {cls.__name__}: {sorted(unknown)}")
    values: dict[str, object] = {}
    for name, value in row.items():
        values[name] = bool(value) if value is not None and _is_bool(hints[name]) else value
    return typing.cast("T", cls(**values))


class Repository:
    """Holds the connection and maps rows. Subclasses add the area's queries."""

    def __init__(self, conn: Connection) -> None:
        self.conn = conn

    def one[T](self, cls: type[T], sql: str, params: Params = ()) -> T | None:
        row = self.conn.execute(sql, params).fetchone()
        return None if row is None else from_row(cls, row)

    def all[T](self, cls: type[T], sql: str, params: Params = ()) -> list[T]:
        return [from_row(cls, row) for row in self.conn.execute(sql, params).fetchall()]

    def run(self, sql: str, params: Params = ()) -> int:
        """Executes a write statement and returns the number of affected rows."""
        return self.conn.execute(sql, params).rowcount


def to_db_bool(value: bool) -> int:
    return 1 if value else 0
