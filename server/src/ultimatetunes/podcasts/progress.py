# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-user progress of podcast episodes (docs/podcasts.md, PLAN T44).

Position, played and "keep" share one `changed_at`, the time it happened on the client: the
newest wins, whatever the arrival order. An update with the same time as the stored one is
applied (the later arrival wins). A time after the server clock counts as now. `updated_at` is
when the server stored it, for incremental sync. Nothing here starts a download.
"""

import base64
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ultimatetunes.core.clock import Clock, format_ts, parse_ts
from ultimatetunes.db.repository import Repository, to_db_bool
from ultimatetunes.errors import InvalidParameter
from ultimatetunes.ids.virtual import is_uuid, is_video_id

EPISODE_PREFIX = "ytepisode:"
# `syncedAt` is set this far back, so a write that was still uncommitted (or stored by another
# replica with a slightly different clock) while a page was read is sent again on the next sync.
SYNC_MARGIN = timedelta(seconds=60)
# Client times are kept inside this range: stored text must stay fixed width and ordered.
_EARLIEST = datetime(1970, 1, 1, tzinfo=UTC)
_LATEST = datetime(9999, 1, 1, tzinfo=UTC)

_PROGRESS = "episode_id, position_ms, played, keep_file, changed_at, updated_at"


@dataclass(frozen=True)
class Progress:
    episode_id: str
    position_ms: int
    played: bool
    keep_file: bool
    changed_at: str
    updated_at: str


@dataclass(frozen=True)
class ProgressUpdate:
    """One reported change. `keep` is None when the client left it unchanged."""

    episode_id: str
    position_ms: int
    played: bool
    keep: bool | None
    changed_at: datetime


@dataclass(frozen=True)
class ProgressResult:
    items: list[Progress]
    unknown: list[str]


@dataclass(frozen=True)
class ProgressPage:
    items: list[Progress]
    next_cursor: str | None
    synced_at: str


@dataclass(frozen=True)
class StartedEpisode:
    """An episode in progress, with what `PodcastEpisode` needs from its show."""

    id: str
    show_id: str
    show_title: str
    title: str
    published_at: str | None
    duration_ms: int | None
    discovered_at: str
    state: str
    size_bytes: int | None
    position_ms: int
    played: bool
    keep_file: bool
    changed_at: str


@dataclass(frozen=True)
class _Id:
    id: str


def _clamp(moment: datetime, latest: datetime = _LATEST) -> datetime:
    # Comparing aware datetimes never overflows, converting an extreme one to UTC can.
    return min(max(moment, _EARLIEST), latest)


class ProgressRepository(Repository):
    def episode_id(self, raw: str) -> str | None:
        """The row id behind an episode UUID or `ytepisode:` id, None when there is none."""
        if raw.startswith(EPISODE_PREFIX):
            value = raw.removeprefix(EPISODE_PREFIX)
            if not is_video_id(value):
                return None
            sql = "SELECT id FROM podcast_episodes WHERE yt_video_id = ?"
        else:
            value = raw.lower()
            if not is_uuid(value):
                return None
            sql = "SELECT id FROM podcast_episodes WHERE id = ?"
        found = self.one(_Id, sql, (value,))
        return None if found is None else found.id

    def get(self, user_id: str, episode_id: str) -> Progress | None:
        return self.one(
            Progress,
            f"SELECT {_PROGRESS} FROM podcast_progress "  # noqa: S608  # nosec B608
            "WHERE user_id = ? AND episode_id = ?",
            (user_id, episode_id),
        )

    def save(self, user_id: str, row: Progress) -> None:
        self.run(
            "INSERT INTO podcast_progress "
            "(user_id, episode_id, position_ms, played, keep_file, changed_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (user_id, episode_id) DO UPDATE SET "
            "position_ms = excluded.position_ms, played = excluded.played, "
            "keep_file = excluded.keep_file, changed_at = excluded.changed_at, "
            "updated_at = excluded.updated_at",
            (
                user_id,
                row.episode_id,
                row.position_ms,
                to_db_bool(row.played),
                to_db_bool(row.keep_file),
                row.changed_at,
                row.updated_at,
            ),
        )

    def stored_since(
        self, user_id: str, since: str, after: tuple[str, str], limit: int
    ) -> list[Progress]:
        """Stored at or after `since` and past the `after` key, oldest first."""
        return self.all(
            Progress,
            f"SELECT {_PROGRESS} FROM podcast_progress "  # noqa: S608  # nosec B608
            "WHERE user_id = ? AND updated_at >= ? "
            "AND (updated_at > ? OR (updated_at = ? AND episode_id > ?)) "
            "ORDER BY updated_at, episode_id LIMIT ?",
            (user_id, since, after[0], after[0], after[1], limit),
        )

    def started(self, user_id: str, limit: int) -> list[StartedEpisode]:
        """Started and not played, the most recently changed first."""
        return self.all(
            StartedEpisode,
            "SELECT e.id, e.show_id, s.title AS show_title, e.title, e.published_at, "
            "e.duration_ms, e.discovered_at, e.state, e.size_bytes, "
            "p.position_ms, p.played, p.keep_file, p.changed_at "
            "FROM podcast_progress p "
            "JOIN podcast_episodes e ON e.id = p.episode_id "
            "JOIN podcast_shows s ON s.id = e.show_id "
            "WHERE p.user_id = ? AND p.played = 0 AND p.position_ms > 0 "
            "ORDER BY p.changed_at DESC, e.id LIMIT ?",
            (user_id, limit),
        )


def report(
    repository: ProgressRepository,
    clock: Clock,
    user_id: str,
    updates: Sequence[ProgressUpdate],
) -> ProgressResult:
    """Applies a batch in order; the caller provides the transaction."""
    now = clock.now()
    stored_at = format_ts(now)
    held: dict[str, Progress] = {}
    unknown: dict[str, None] = {}
    for update in updates:
        episode_id = repository.episode_id(update.episode_id)
        if episode_id is None:
            unknown[update.episode_id] = None
            continue
        current = repository.get(user_id, episode_id)
        changed_at = format_ts(_clamp(update.changed_at, now))
        if current is not None and changed_at < current.changed_at:
            held[episode_id] = current
            continue
        keep = update.keep
        if keep is None:
            keep = current is not None and current.keep_file
        row = Progress(episode_id, update.position_ms, update.played, keep, changed_at, stored_at)
        # A repeat changes nothing, so it is not sent to the other devices again.
        if current is not None and _same(current, row):
            held[episode_id] = current
            continue
        repository.save(user_id, row)
        held[episode_id] = row
    return ProgressResult(list(held.values()), list(unknown))


def _same(a: Progress, b: Progress) -> bool:
    return (a.position_ms, a.played, a.keep_file, a.changed_at) == (
        b.position_ms,
        b.played,
        b.keep_file,
        b.changed_at,
    )


def _encode_cursor(row: Progress) -> str:
    return base64.urlsafe_b64encode(f"{row.updated_at} {row.episode_id}".encode()).decode()


def _decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        text = base64.b64decode(cursor, altchars=b"-_", validate=True).decode()
        updated_at, episode_id = text.split(" ")
        parse_ts(updated_at)
    except ValueError as exc:  # also binascii.Error and UnicodeDecodeError
        raise InvalidParameter("Invalid: cursor") from exc
    if not is_uuid(episode_id):
        raise InvalidParameter("Invalid: cursor")
    return updated_at, episode_id


def page(  # noqa: PLR0913 - the query parameters of the contract
    repository: ProgressRepository,
    clock: Clock,
    user_id: str,
    *,
    since: datetime | None,
    cursor: str | None,
    limit: int,
) -> ProgressPage:
    synced_at = format_ts(clock.now() - SYNC_MARGIN)
    after = ("", "") if cursor is None else _decode_cursor(cursor)
    lower = "" if since is None else format_ts(_clamp(since))
    rows = repository.stored_since(user_id, lower, after, limit + 1)
    items = rows[:limit]
    next_cursor = _encode_cursor(items[-1]) if len(rows) > limit else None
    return ProgressPage(items, next_cursor, synced_at)
