# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Typed row mapping and the repository base."""

from dataclasses import dataclass
from pathlib import Path

import pytest

from ultimatetunes.db import Database, Repository, from_row
from ultimatetunes.db.repository import to_db_bool


@dataclass(frozen=True)
class Item:
    id: str
    flag: bool
    maybe: bool | None
    count: int


class ItemRepository(Repository):
    def add(self, item: Item) -> int:
        return self.run(
            "INSERT INTO items (id, flag, maybe, count) VALUES (?, ?, ?, ?)",
            (
                item.id,
                to_db_bool(item.flag),
                None if item.maybe is None else to_db_bool(item.maybe),
                item.count,
            ),
        )

    def get(self, item_id: str) -> Item | None:
        return self.one(Item, "SELECT id, flag, maybe, count FROM items WHERE id = ?", (item_id,))

    def list(self) -> list[Item]:
        return self.all(Item, "SELECT id, flag, maybe, count FROM items ORDER BY id")


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database.sqlite(tmp_path / "ut.db")
    with database.transaction() as conn:
        conn.execute(
            "CREATE TABLE items (id TEXT NOT NULL PRIMARY KEY, flag INTEGER NOT NULL,"
            " maybe INTEGER, count BIGINT NOT NULL)"
        )
    return database


def test_round_trip_maps_booleans(db: Database) -> None:
    with db.transaction() as conn:
        repo = ItemRepository(conn)
        assert repo.add(Item("b", flag=True, maybe=None, count=2)) == 1
        repo.add(Item("a", flag=False, maybe=True, count=1))
    with db.read() as conn:
        repo = ItemRepository(conn)
        assert repo.get("b") == Item("b", flag=True, maybe=None, count=2)
        assert repo.get("zz") is None
        assert [i.id for i in repo.list()] == ["a", "b"]
        assert repo.list()[0].maybe is True


def test_from_row_refuses_unknown_columns_and_non_dataclasses() -> None:
    with pytest.raises(ValueError, match="not in Item"):
        from_row(Item, {"id": "a", "flag": 1, "maybe": None, "count": 1, "extra": 2})
    with pytest.raises(TypeError, match="not a dataclass"):
        from_row(int, {"x": 1})
