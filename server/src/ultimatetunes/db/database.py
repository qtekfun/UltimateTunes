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
"""

import queue
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from ultimatetunes.db.driver import Connection, connect_sqlite

DEFAULT_READERS = 4


class Database:
    def __init__(self, opener: Callable[[], Connection], *, readers: int = DEFAULT_READERS) -> None:
        if readers < 1:
            raise ValueError("at least one reader connection is needed")
        self._open = opener
        self._write_lock = threading.Lock()
        self._writer: Connection | None = None
        self._readers: queue.LifoQueue[Connection] = queue.LifoQueue()
        self._reader_slots = threading.BoundedSemaphore(readers)
        self._all: list[Connection] = []
        self._all_lock = threading.Lock()
        self._closed = False

    @classmethod
    def sqlite(cls, path: Path, *, readers: int = DEFAULT_READERS) -> "Database":
        return cls(lambda: connect_sqlite(path), readers=readers)

    def _new(self) -> Connection:
        if self._closed:
            raise RuntimeError("database is closed")
        conn = self._open()
        with self._all_lock:
            self._all.append(conn)
        return conn

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        """The single writer, inside a transaction committed on success."""
        with self._write_lock:
            if self._writer is None:
                self._writer = self._new()
            with self._writer.transaction():
                yield self._writer

    @contextmanager
    def read(self) -> Iterator[Connection]:
        """A reader connection in autocommit mode. Do not write through it."""
        with self._reader_slots:
            try:
                conn = self._readers.get_nowait()
            except queue.Empty:
                conn = self._new()
            try:
                yield conn
            finally:
                self._readers.put(conn)

    def close(self) -> None:
        """Closes every connection opened so far. The database cannot be used afterwards."""
        self._closed = True
        with self._all_lock:
            conns, self._all = self._all, []
        for conn in conns:
            conn.close()
        self._writer = None
