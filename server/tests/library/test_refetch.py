# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`refetch-failed`: requeue failed downloads and, with `--truncated`, short archived files."""

import io
from pathlib import Path

import pytest

from ultimatetunes.core.clock import FakeClock, format_ts
from ultimatetunes.core.storage import LocalLibraryStore
from ultimatetunes.db import Database, migrate
from ultimatetunes.jobs.queue import SqliteJobQueue
from ultimatetunes.library import cli
from ultimatetunes.library.refetch import Refetcher
from ultimatetunes.settings import Settings

CONTRACTS = Path(__file__).resolve().parents[2].parent / "contracts"


def _add_track(  # noqa: PLR0913 - the columns of one track row
    db: Database,
    clock: FakeClock,
    track_id: str,
    video_id: str,
    *,
    status: str,
    path: str | None = None,
    size_bytes: int | None = None,
) -> None:
    now = format_ts(clock.now())
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO tracks (id, status, title, title_norm, artist_name, yt_video_id,"
            " path, size_bytes, format, content_type, archived_at, created_at, updated_at)"
            " VALUES (?, ?, 'Glass Orchard', 'glass orchard', 'The Paper Lanterns', ?, ?, ?,"
            " 'opus', 'audio/ogg', ?, ?, ?)",
            (track_id, status, video_id, path, size_bytes, now if path else None, now, now),
        )


def _add_job(db: Database, clock: FakeClock, track_id: str, video_id: str, *, state: str) -> str:
    now = format_ts(clock.now())
    job_id = f"job-{track_id}"
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO jobs (id, kind, track_id, yt_video_id, state, priority, attempts,"
            " error_code, created_at, updated_at) VALUES (?, 'download', ?, ?, ?, 10, 3,"
            " 'network_error', ?, ?)",
            (job_id, track_id, video_id, state, now, now),
        )
    return job_id


def _job_state(db: Database, job_id: str) -> str:
    with db.read() as conn:
        return str(conn.execute("SELECT state FROM jobs WHERE id = ?", (job_id,)).scalar())


def _track(db: Database, track_id: str) -> dict[str, object]:
    with db.read() as conn:
        row = conn.execute(
            "SELECT status, path, size_bytes FROM tracks WHERE id = ?", (track_id,)
        ).fetchone()
    assert row is not None
    return {"status": row["status"], "path": row["path"], "size_bytes": row["size_bytes"]}


@pytest.fixture
def library(tmp_path: Path) -> LocalLibraryStore:
    root = tmp_path / "music"
    root.mkdir(exist_ok=True)
    return LocalLibraryStore(root)


@pytest.fixture
def refetcher(db: Database, clock: FakeClock, library: LocalLibraryStore) -> Refetcher:
    return Refetcher(db, SqliteJobQueue(db, clock), library, clock)


def test_requeues_failed_downloads(db: Database, clock: FakeClock, refetcher: Refetcher) -> None:
    _add_track(db, clock, "t1", "Rb8Tn3ZcYv0", status="failed")
    job_id = _add_job(db, clock, "t1", "Rb8Tn3ZcYv0", state="failed")
    result = refetcher.refetch(truncated=False, dry_run=False)
    assert (result.failed, result.truncated) == (1, 0)
    assert _job_state(db, job_id) == "queued"
    assert _track(db, "t1")["status"] == "pending"


def test_dry_run_changes_nothing(db: Database, clock: FakeClock, refetcher: Refetcher) -> None:
    _add_track(db, clock, "t1", "Rb8Tn3ZcYv0", status="failed")
    job_id = _add_job(db, clock, "t1", "Rb8Tn3ZcYv0", state="failed")
    result = refetcher.refetch(truncated=True, dry_run=True)
    assert (result.failed, result.truncated) == (1, 0)
    assert _job_state(db, job_id) == "failed"
    assert _track(db, "t1")["status"] == "failed"


def test_cancelled_downloads_are_left_alone(
    db: Database, clock: FakeClock, refetcher: Refetcher
) -> None:
    _add_track(db, clock, "t1", "Rb8Tn3ZcYv0", status="failed")
    job_id = _add_job(db, clock, "t1", "Rb8Tn3ZcYv0", state="cancelled")
    result = refetcher.refetch(truncated=True, dry_run=False)
    assert (result.failed, result.truncated) == (0, 0)
    assert _job_state(db, job_id) == "cancelled"


def test_truncated_ready_track_is_refetched(
    db: Database, clock: FakeClock, library: LocalLibraryStore, refetcher: Refetcher
) -> None:
    _add_track(db, clock, "t2", "Wq5Jd7HsKe2", status="ready", path="A/song.opus", size_bytes=100)
    (library.root / "A").mkdir()
    (library.root / "A" / "song.opus").write_bytes(b"x" * 40)  # short: 40 of 100
    _add_job(db, clock, "t2", "Wq5Jd7HsKe2", state="ready")
    result = refetcher.refetch(truncated=True, dry_run=False)
    assert (result.failed, result.truncated) == (0, 1)
    track = _track(db, "t2")
    assert (track["status"], track["path"], track["size_bytes"]) == ("pending", None, None)
    assert not (library.root / "A" / "song.opus").exists()  # the broken file is replaced
    with db.read() as conn:
        job = conn.execute(
            "SELECT state FROM jobs WHERE track_id = 't2' AND kind = 'download'"
        ).fetchone()
    assert job is not None
    assert job["state"] == "queued"  # a fresh download


def test_intact_ready_tracks_are_untouched(
    db: Database, clock: FakeClock, library: LocalLibraryStore, refetcher: Refetcher
) -> None:
    _add_track(db, clock, "t2", "Wq5Jd7HsKe2", status="ready", path="ok.opus", size_bytes=5)
    (library.root / "ok.opus").write_bytes(b"xxxxx")  # exactly 5 bytes
    result = refetcher.refetch(truncated=True, dry_run=False)
    assert result.truncated == 0
    assert _track(db, "t2")["status"] == "ready"
    assert (library.root / "ok.opus").exists()


def test_a_missing_archived_file_counts_as_truncated(
    db: Database, clock: FakeClock, refetcher: Refetcher
) -> None:
    _add_track(db, clock, "t2", "Wq5Jd7HsKe2", status="ready", path="gone.opus", size_bytes=5)
    result = refetcher.refetch(truncated=True, dry_run=False)
    assert result.truncated == 1
    assert _track(db, "t2")["status"] == "pending"


def test_without_the_flag_truncated_files_are_ignored(
    db: Database, clock: FakeClock, library: LocalLibraryStore, refetcher: Refetcher
) -> None:
    _add_track(db, clock, "t1", "Rb8Tn3ZcYv0", status="failed")
    _add_job(db, clock, "t1", "Rb8Tn3ZcYv0", state="failed")
    _add_track(db, clock, "t2", "Wq5Jd7HsKe2", status="ready", path="A/song.opus", size_bytes=100)
    (library.root / "A").mkdir()
    (library.root / "A" / "song.opus").write_bytes(b"x" * 40)
    result = refetcher.refetch(truncated=False, dry_run=False)
    assert (result.failed, result.truncated) == (1, 0)
    assert _track(db, "t2")["status"] == "ready"  # left for a run with --truncated


# ------------------------------------------------------------------ the CLI command


@pytest.fixture
def cli_settings(tmp_path: Path, clock: FakeClock) -> Settings:
    data = tmp_path / "data"
    music = tmp_path / "music"
    for directory in (data, music):
        directory.mkdir(exist_ok=True)
    settings = Settings(data_dir=data, music_dir=music, fake_youtube=True)
    conn = migrate.connect(settings.database_file)
    migrate.migrate(conn, CONTRACTS / "db" / "migrations", clock)
    conn.close()
    return settings


def _run(settings: Settings, args: list[str]) -> tuple[int, str]:
    out = io.StringIO()
    code = cli.run_refetch(settings, args, out=out)
    return code, out.getvalue()


def test_cli_requeues_and_reports(cli_settings: Settings, clock: FakeClock) -> None:
    db = Database.sqlite(cli_settings.database_file)
    try:
        _add_track(db, clock, "t1", "Rb8Tn3ZcYv0", status="failed")
        _add_job(db, clock, "t1", "Rb8Tn3ZcYv0", state="failed")
    finally:
        db.close()
    code, text = _run(cli_settings, ["--truncated"])
    assert code == 0
    assert "requeued 1 failed, 0 truncated" in text


def test_cli_dry_run_wording(cli_settings: Settings) -> None:
    code, text = _run(cli_settings, ["--dry-run"])
    assert code == 0
    assert text.startswith("would requeue 0 failed download")


def test_cli_rejects_unknown_arguments(cli_settings: Settings) -> None:
    code, text = _run(cli_settings, ["--nope"])
    assert code == 2
    assert text.startswith("usage:")


def test_cli_rejects_repeated_arguments(cli_settings: Settings) -> None:
    code, _ = _run(cli_settings, ["--dry-run", "--dry-run"])
    assert code == 2
