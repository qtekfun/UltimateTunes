-- SPDX-FileCopyrightText: 2026 UltimateTunes contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- 0703_jobs_episodes (PLAN T41): the download queue also holds podcast episodes (kind 'episode',
-- episode_id set, track_id NULL). One queue keeps one lease logic and the streaming code.
-- Widening the CHECK and dropping NOT NULL needs a new table, a data copy and a rename
-- (contracts/db/README.md). No table references jobs, so dropping the old one deletes nothing else.
-- It runs after every 0100-0699 migration on a new database but not on an existing one: from
-- now on, changes to jobs go in migrations numbered above this one.
CREATE TABLE jobs_new (
    id TEXT NOT NULL PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('download', 'episode')),
    track_id TEXT REFERENCES tracks (id) ON DELETE CASCADE,
    episode_id TEXT UNIQUE REFERENCES podcast_episodes (id) ON DELETE CASCADE,
    yt_video_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('queued', 'downloading', 'tagging', 'ready', 'failed', 'cancelled')),
    priority INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    not_before TEXT,
    lease_id TEXT UNIQUE,
    lease_owner TEXT,
    lease_expires_at TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK (cancel_requested IN (0, 1)),
    progress DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (progress >= 0 AND progress <= 1),
    bytes_downloaded BIGINT,
    expected_size BIGINT,
    part_path TEXT,
    final_path TEXT,
    finished INTEGER NOT NULL DEFAULT 0 CHECK (finished IN (0, 1)),
    progressive INTEGER NOT NULL DEFAULT 0 CHECK (progressive IN (0, 1)),
    format_id TEXT,
    content_type TEXT,
    library_path TEXT UNIQUE,
    merge_into_track_id TEXT REFERENCES tracks (id) ON DELETE SET NULL,
    last_lease_id TEXT,
    last_outcome TEXT,
    error_code TEXT,
    error_message TEXT,
    requested_by TEXT REFERENCES users (id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    attempt_seq INTEGER NOT NULL DEFAULT 0,
    previous_format_id TEXT,
    previous_expected_size BIGINT,
    lease_seconds INTEGER,
    placed_path TEXT,
    placed_sha256 TEXT,
    UNIQUE (kind, track_id),
    CHECK ((kind = 'download' AND track_id IS NOT NULL AND episode_id IS NULL)
        OR (kind = 'episode' AND episode_id IS NOT NULL AND track_id IS NULL))
);

INSERT INTO jobs_new (
    id, kind, track_id, yt_video_id, state, priority, attempts, max_attempts, not_before, lease_id,
    lease_owner, lease_expires_at, cancel_requested, progress, bytes_downloaded, expected_size,
    part_path, final_path, finished, progressive, format_id, content_type, library_path,
    merge_into_track_id, last_lease_id, last_outcome, error_code, error_message, requested_by,
    created_at, updated_at, started_at, finished_at, attempt_seq, previous_format_id,
    previous_expected_size, lease_seconds, placed_path, placed_sha256
)
SELECT
    id, kind, track_id, yt_video_id, state, priority, attempts, max_attempts, not_before, lease_id,
    lease_owner, lease_expires_at, cancel_requested, progress, bytes_downloaded, expected_size,
    part_path, final_path, finished, progressive, format_id, content_type, library_path,
    merge_into_track_id, last_lease_id, last_outcome, error_code, error_message, requested_by,
    created_at, updated_at, started_at, finished_at, attempt_seq, previous_format_id,
    previous_expected_size, lease_seconds, placed_path, placed_sha256
FROM jobs;

DROP TABLE jobs;

ALTER TABLE jobs_new RENAME TO jobs;

CREATE INDEX ix_jobs_claim ON jobs (state, priority, created_at);
CREATE INDEX ix_jobs_lease_expiry ON jobs (state, lease_expires_at);
CREATE INDEX ix_jobs_video ON jobs (yt_video_id);
CREATE INDEX ix_jobs_requested_by ON jobs (requested_by, state);
CREATE INDEX ix_jobs_updated ON jobs (updated_at);
