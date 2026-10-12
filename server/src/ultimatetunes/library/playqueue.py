# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The saved play queue (RF-09, OpenSubsonic `savePlayQueue` / `getPlayQueue`).

Saving stores the raw item ids (library UUIDs or `yt:` ids, after validation) and never
materializes or downloads anything (contracts/ids.md). Reading resolves them: an archived
item shows as its library song (and `current` follows it), a pending one as its `yt:` song, an
unknown `yt:` id from the catalog (or a placeholder when the catalog cannot answer), and a
library id that no longer exists is left out. Saving no ids clears the queue.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from starlette.concurrency import run_in_threadpool

from ultimatetunes.core.clock import format_ts
from ultimatetunes.errors import InvalidParameter
from ultimatetunes.ids.virtual import LibraryId, parse_kind
from ultimatetunes.library.render import Obj, compact
from ultimatetunes.library.songs import check_count, resolve_children

if TYPE_CHECKING:
    from ultimatetunes.core.services import Services

MAX_CLIENT = 64


@dataclass(frozen=True)
class SavedQueue:
    current: str | None
    position_ms: int
    changed_at: str
    changed_by: str
    items: list[str]


def _canonical(raw: str) -> str:
    parsed = parse_kind(raw, "song")
    return parsed.value if isinstance(parsed, LibraryId) else parsed.text


class PlayQueue:
    def __init__(self, services: "Services", user_id: str, username: str) -> None:
        self._services = services
        self._user = user_id
        self._username = username

    def save(
        self, ids: Sequence[str], *, current: str | None, position_ms: int, client: str | None
    ) -> None:
        check_count(ids)
        if position_ms < 0:
            raise InvalidParameter("position must be zero or more")
        items = [_canonical(i) for i in ids]
        current_id = _canonical(current) if current else None
        now = format_ts(self._services.clock.now())
        with self._services.db.transaction() as conn:
            conn.execute("DELETE FROM play_queue_entries WHERE user_id = ?", (self._user,))
            conn.execute("DELETE FROM play_queues WHERE user_id = ?", (self._user,))
            if not items:
                return
            conn.execute(
                "INSERT INTO play_queues (user_id, current_item_id, position_ms, changed_at,"
                " changed_by) VALUES (?, ?, ?, ?, ?)",
                (self._user, current_id, position_ms, now, (client or "")[:MAX_CLIENT]),
            )
            for index, item in enumerate(items):
                conn.execute(
                    "INSERT INTO play_queue_entries (user_id, idx, item_id) VALUES (?, ?, ?)",
                    (self._user, index, item),
                )

    def _load(self) -> SavedQueue | None:
        with self._services.db.read() as conn:
            row = conn.execute(
                "SELECT current_item_id, position_ms, changed_at, changed_by FROM play_queues"
                " WHERE user_id = ?",
                (self._user,),
            ).fetchone()
            if row is None:
                return None
            entries = conn.execute(
                "SELECT item_id FROM play_queue_entries WHERE user_id = ? ORDER BY idx",
                (self._user,),
            ).fetchall()
        current = row["current_item_id"]
        position = row["position_ms"]
        return SavedQueue(
            current=None if current is None else str(current),
            position_ms=position if isinstance(position, int) else 0,
            changed_at=str(row["changed_at"]),
            changed_by=str(row["changed_by"]),
            items=[str(e["item_id"]) for e in entries],
        )

    async def get(self) -> Obj | None:
        saved = await run_in_threadpool(self._load)
        if saved is None:
            return None
        resolved = await resolve_children(self._services, self._user, saved.items)
        current = saved.current
        for raw, child in resolved:
            if raw == saved.current:
                current = str(child["id"])
                break
        return compact(
            {
                "current": current,
                "position": saved.position_ms,
                "username": self._username,
                "changed": saved.changed_at,
                "changedBy": saved.changed_by,
                "entry": [child for _, child in resolved],
            }
        )
