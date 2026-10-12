# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Query planner statistics (issue #54).

Without `sqlite_stat1` SQLite answered the `EXISTS (... ta.album_id = al.id AND ta.status =
'ready')` of the artist list through `ix_tracks_status` (every track is ready), a scan of the
whole table per album: getArtists took 20 s on 50,000 tracks. These tests seed a library where
that plan is the default and check that the statistics hooks make the planner pick the
per-album index, for a database filled before the api opens it, for one filled while it runs
and after `migrate`.
"""

import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from pathlib import Path

import pytest

from ultimatetunes.db import Database, DatabaseError, migrate
from ultimatetunes.db.driver import (
    SQLITE_BUSY_TIMEOUT_MS,
    Connection,
    Dialect,
    Params,
    Result,
    connect_sqlite,
)
from ultimatetunes.library.repository import _ARTISTS, _ARTISTS_GROUP

CONTRACT_MIGRATIONS = Path(__file__).resolve().parents[3] / "contracts" / "db" / "migrations"
TS = "2026-01-01T00:00:00Z"
BUSY_S = SQLITE_BUSY_TIMEOUT_MS / 1000
ARTISTS_SQL = _ARTISTS + _ARTISTS_GROUP + " ORDER BY ar.name_norm, ar.id"


Tx = Callable[[], AbstractContextManager[Connection]]


def on(conn: Connection) -> Tx:
    """`conn` inside its own transaction, as `Database.transaction` gives the writer."""

    @contextmanager
    def tx() -> Iterator[Connection]:
        with conn.transaction():
            yield conn

    return tx


def seed(tx: Tx, albums: int = 200, per_album: int = 10) -> None:
    """A library where every track is ready: `ix_tracks_status` has no selectivity at all."""
    with tx() as conn:
        for a in range(albums // 2):
            conn.execute(
                "INSERT INTO artists (id, name, name_norm, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (f"ar{a}", f"Artist {a}", f"artist {a}", TS, TS),
            )
        for al in range(albums):
            conn.execute(
                "INSERT INTO albums (id, artist_id, name, name_norm, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (f"al{al}", f"ar{al // 2}", f"Album {al}", f"album {al}", TS, TS),
            )
            for t in range(per_album):
                conn.execute(
                    "INSERT INTO tracks (id, status, title, title_norm, artist_id, album_id,"
                    " artist_name, disc_number, track_number, created_at, updated_at)"
                    " VALUES (?, 'ready', ?, ?, ?, ?, ?, 1, ?, ?, ?)",
                    (f"t{al}_{t}", "T", "t", f"ar{al // 2}", f"al{al}", "A", t, TS, TS),
                )


def album_lookup_index(conn: Connection) -> str:
    """The index the artist list uses to find the ready tracks of an album."""
    plan = conn.execute("EXPLAIN QUERY PLAN " + ARTISTS_SQL, ("u",)).fetchall()
    for row in plan:
        detail = str(row["detail"])
        if detail.startswith("SEARCH ta "):
            return detail.split(" USING INDEX ")[1].split(" ", maxsplit=1)[0]
    raise AssertionError(f"no lookup of ta in {plan}")


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "ut.db"


def migrated_without_stats(path: Path) -> None:
    conn = connect_sqlite(path)
    try:
        migrate.migrate(conn, CONTRACT_MIGRATIONS)
        conn.execute(
            "DROP TABLE IF EXISTS sqlite_stat1"
        )  # as every database created before the fix
        seed(on(conn))
    finally:
        conn.close()


def test_without_statistics_the_planner_picks_the_status_index(path: Path) -> None:
    # Documents the bug the other tests guard against: if this stops holding, the regression
    # tests below no longer prove anything.
    migrated_without_stats(path)
    conn = connect_sqlite(path)
    try:
        assert album_lookup_index(conn) == "ix_tracks_status"
    finally:
        conn.close()


def test_a_database_filled_before_opening_gets_statistics_on_first_use(path: Path) -> None:
    migrated_without_stats(path)
    db = Database.sqlite(path, readers=1)
    try:
        with db.read() as conn:
            assert album_lookup_index(conn) == "ix_tracks_album"
    finally:
        db.close()


def test_migrate_leaves_statistics_behind(path: Path) -> None:
    conn = connect_sqlite(path)
    try:
        migrate.migrate(conn, CONTRACT_MIGRATIONS)
        assert conn.table_exists("sqlite_stat1")
        seed(on(conn))
        migrate.migrate(conn, CONTRACT_MIGRATIONS)  # nothing pending: still refreshes
        assert album_lookup_index(conn) == "ix_tracks_album"
    finally:
        conn.close()


def test_readers_pick_up_statistics_the_writer_refreshed_while_running(path: Path) -> None:
    conn = connect_sqlite(path)
    migrate.migrate(conn, CONTRACT_MIGRATIONS)  # statistics of an empty library
    conn.close()
    db = Database.sqlite(path, readers=1, optimize_every=2)
    try:
        with db.read() as reader:
            assert album_lookup_index(reader) == "ix_tracks_status"  # empty tables, stale
        with db.transaction() as writer:
            writer.execute("SELECT 1")
        seed(db.transaction)  # the library grows through the api's writer
        with db.read() as reader:
            assert album_lookup_index(reader) == "ix_tracks_album"
    finally:
        db.close()


def test_close_refreshes_statistics_of_what_the_writer_wrote(path: Path) -> None:
    conn = connect_sqlite(path)
    migrate.migrate(conn, CONTRACT_MIGRATIONS)
    conn.close()
    db = Database.sqlite(path, readers=1)  # default interval: no refresh while seeding
    seed(db.transaction)
    db.close()  # e.g. the end of `ultimatetunes scan-library`
    raw = sqlite3.connect(path)
    try:
        rows = raw.execute("SELECT COUNT(*) FROM sqlite_stat1 WHERE tbl = 'tracks'").fetchone()
        assert rows[0] > 0
    finally:
        raw.close()
    conn = connect_sqlite(path)
    try:
        assert album_lookup_index(conn) == "ix_tracks_album"
    finally:
        conn.close()


def test_a_stale_reader_is_replaced_while_another_connection_writes(path: Path) -> None:
    # Reloading statistics in place (`ANALYZE sqlite_schema`) waits for the write lock, up to
    # the 5 s busy timeout; a new connection only reads them.
    migrated_without_stats(path)
    db = Database.sqlite(path, readers=1, optimize_every=1)
    other = sqlite3.connect(path, isolation_level=None)
    try:
        with db.read():
            pass
        with db.transaction() as writer:  # refreshes after it: the reader is now stale
            writer.execute("DELETE FROM tracks WHERE id = 't0_0'")
        other.execute("BEGIN IMMEDIATE")  # e.g. `scan-library` writing meanwhile
        started = time.monotonic()
        with db.read() as reader:
            assert album_lookup_index(reader) == "ix_tracks_album"
        assert time.monotonic() - started < BUSY_S / 2
    finally:
        other.close()
        db.close()


def test_close_does_not_wait_for_another_writer(
    path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    conn = connect_sqlite(path)
    migrate.migrate(conn, CONTRACT_MIGRATIONS)
    conn.close()
    db = Database.sqlite(path, readers=1)
    seed(db.transaction)  # statistics are stale: the refresh on close has to write
    other = sqlite3.connect(path, isolation_level=None)
    try:
        other.execute("BEGIN IMMEDIATE")
        started = time.monotonic()
        db.close()
        assert time.monotonic() - started < BUSY_S / 2
    finally:
        other.close()
    assert "statistics failed" in caplog.text


class FlakyStats:
    """A connection whose refresh fails, recording what happens to it in `log`."""

    dialect: Dialect = "sqlite"

    def __init__(self, log: list[str] | None = None) -> None:
        self.log = log if log is not None else []
        self.optimized = 0
        self.log.append("open")

    def execute(self, sql: str, params: Params = ()) -> Result:
        return Result([], 0)

    def transaction(self) -> AbstractContextManager[None]:
        return nullcontext()

    def table_exists(self, name: str) -> bool:
        return False

    def optimize(self, *, wait_ms: int | None = None) -> None:
        self.optimized += 1
        raise DatabaseError("database is locked")

    def close(self) -> None:
        self.log.append("close")


def test_failed_refreshes_are_logged_and_never_fail_the_caller(
    caplog: pytest.LogCaptureFixture,
) -> None:
    conns: list[FlakyStats] = []

    def opener() -> Connection:
        conns.append(FlakyStats())
        return conns[-1]

    db = Database(opener, readers=1, optimize_every=1)
    with db.read() as conn:
        assert conn.execute("SELECT 1").fetchall() == []
    with db.read():
        pass
    with db.transaction():
        pass
    db.optimize()
    db.close()
    # First use, after the write, explicit, close; nothing refreshed: the reader is kept.
    writer, reader = conns
    assert writer.optimized == 4
    assert reader.log == ["open", "close"]
    assert "statistics failed" in caplog.text


def test_statistics_are_refreshed_on_first_use_every_n_writes_and_on_close() -> None:
    log: list[str] = []

    class Counting(FlakyStats):
        def optimize(self, *, wait_ms: int | None = None) -> None:
            self.log.append(f"optimize {wait_ms}")

    def opener() -> Connection:
        return Counting(log)

    db = Database(opener, readers=1, optimize_every=3)
    with db.read():
        pass
    with db.read():
        pass
    assert log == ["open", "optimize None", "open"]  # writer, its refresh, the reader
    for _ in range(3):
        with db.transaction():
            pass
    with db.read():
        pass
    # The stale reader is closed and replaced by one that loads the new statistics.
    assert log[3:] == ["optimize None", "close", "open"]
    db.close()
    db.close()  # closing twice does not refresh again
    assert log[6:] == ["optimize 200", "close", "close"]


def test_close_skips_the_refresh_while_the_writer_is_busy() -> None:
    log: list[str] = []
    db = Database(lambda: FlakyStats(log), readers=1)
    with db.transaction():
        pass
    assert db._write_lock.acquire(timeout=1)  # a write still running in another thread
    try:
        db.close()
    finally:
        db._write_lock.release()
    assert log == ["open", "close"]  # the first-use refresh only (it failed, not logged here)


def test_optimize_every_must_be_positive() -> None:
    opener: Callable[[], Connection] = FlakyStats
    with pytest.raises(ValueError, match="optimize_every"):
        Database(opener, optimize_every=0)
