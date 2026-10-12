# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Connection management for the api: one writer, a few readers, opened lazily.

SQLite in WAL mode lets readers run while one writer writes. `Database` keeps exactly one
writer connection behind a lock (so writes never fight over `SQLITE_BUSY`) and a small pool of
reader connections. Nothing is opened until first use, so `/healthz` works without a database.

    with db.transaction() as conn:   # BEGIN IMMEDIATE ... COMMIT, serialized
        TrackRepository(conn).create(...)
        AliasRepository(conn).add(...)
    with db.read() as conn:          # autocommit reads, concurrent
        TrackRepository(conn).get(track_id)

Planner statistics (issue #54): the writer refreshes them (`Connection.optimize`) on first use,
every `optimize_every` write transactions and on close, as SQLite recommends for long-lived
connections; readers reload them before their next use after a refresh, because SQLite caches
statistics per connection. A failed refresh is logged and never fails the caller.
"""

import logging
import queue
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from ultimatetunes.db.driver import Connection, DatabaseError, connect_sqlite

DEFAULT_READERS = 4
# Write transactions between two statistics refreshes. `PRAGMA optimize` is a no-op in a few
# microseconds when no table changed much, and analyzes with a row limit when one did.
DEFAULT_OPTIMIZE_EVERY = 1000

log = logging.getLogger(__name__)


class Database:
    def __init__(
        self,
        opener: Callable[[], Connection],
        *,
        readers: int = DEFAULT_READERS,
        optimize_every: int = DEFAULT_OPTIMIZE_EVERY,
    ) -> None:
        if readers < 1:
            raise ValueError("at least one reader connection is needed")
        if optimize_every < 1:
            raise ValueError("optimize_every must be positive")
        self._open = opener
        self._write_lock = threading.Lock()
        self._writer: Connection | None = None
        self._readers: queue.LifoQueue[Connection] = queue.LifoQueue()
        self._reader_slots = threading.BoundedSemaphore(readers)
        self._all: list[Connection] = []
        self._all_lock = threading.Lock()
        self._closed = False
        self._optimize_every = optimize_every
        self._writes_since_optimize = 0
        self._optimized_once = False
        # Bumped by every refresh; each reader remembers the generation it last loaded.
        self._stats_generation = 0
        self._reader_generation: dict[int, int] = {}

    @classmethod
    def sqlite(
        cls,
        path: Path,
        *,
        readers: int = DEFAULT_READERS,
        optimize_every: int = DEFAULT_OPTIMIZE_EVERY,
    ) -> "Database":
        return cls(lambda: connect_sqlite(path), readers=readers, optimize_every=optimize_every)

    def _new(self) -> Connection:
        if self._closed:
            raise RuntimeError("database is closed")
        conn = self._open()
        with self._all_lock:
            self._all.append(conn)
        return conn

    def _writer_conn(self) -> Connection:
        """The writer, opened on first use; the caller holds the write lock."""
        if self._writer is None:
            self._writer = self._new()
        return self._writer

    def _optimize_locked(self) -> None:
        """Refreshes the statistics through the writer; the caller holds the write lock."""
        self._optimized_once = True
        self._writes_since_optimize = 0
        try:
            self._writer_conn().optimize()
        except DatabaseError:
            log.warning("refreshing the query planner statistics failed", exc_info=True)
            return
        self._stats_generation += 1

    def optimize(self) -> None:
        """Refreshes the planner statistics now (e.g. after a bulk import)."""
        with self._write_lock:
            self._optimize_locked()

    def _ensure_optimized(self) -> None:
        # Once per Database, before the first query: a database that never had statistics
        # (or was filled since) gets them before anyone plans against it.
        if not self._optimized_once:
            with self._write_lock:
                if not self._optimized_once:
                    self._optimize_locked()

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        """The single writer, inside a transaction committed on success."""
        self._ensure_optimized()
        with self._write_lock:
            writer = self._writer_conn()
            with writer.transaction():
                yield writer
            self._writes_since_optimize += 1
            if self._writes_since_optimize >= self._optimize_every:
                self._optimize_locked()

    def _fresh(self, conn: Connection) -> Connection:
        """`conn` with the current statistics loaded."""
        generation = self._stats_generation
        if self._reader_generation.get(id(conn)) != generation:
            try:
                conn.reload_statistics()
            except DatabaseError:
                log.warning("reloading the query planner statistics failed", exc_info=True)
            else:
                self._reader_generation[id(conn)] = generation
        return conn

    @contextmanager
    def read(self) -> Iterator[Connection]:
        """A reader connection in autocommit mode. Do not write through it."""
        self._ensure_optimized()
        with self._reader_slots:
            try:
                conn = self._readers.get_nowait()
            except queue.Empty:
                conn = self._new()
            try:
                yield self._fresh(conn)
            finally:
                self._readers.put(conn)

    def close(self) -> None:
        """Refreshes the statistics (SQLite's advice before closing a long-lived connection),
        then closes every connection opened so far. The database cannot be used afterwards."""
        with self._write_lock:
            if self._writer is not None and not self._closed:
                self._optimize_locked()
        self._closed = True
        with self._all_lock:
            conns, self._all = self._all, []
        for conn in conns:
            conn.close()
        self._writer = None
