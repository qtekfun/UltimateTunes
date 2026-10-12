-- SPDX-FileCopyrightText: 2026 UltimateTunes contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- 0001_init: every v1 table implied by SPEC.md (PLAN T02).
--
-- Portable subset (runs unchanged on SQLite and PostgreSQL), see contracts/db/README.md:
-- ids are TEXT (UUIDv7, contracts/ids.md), integers are INTEGER or BIGINT,
-- fractional numbers are DOUBLE PRECISION (REAL affinity on SQLite),
-- booleans are INTEGER 0/1 with a CHECK, timestamps are TEXT in the fixed-width UTC
-- format YYYY-MM-DDTHH:MM:SS.mmmZ (text order is time order),
-- no AUTOINCREMENT, SERIAL, JSON functions, partial indexes or DEFAULT expressions,
-- every timestamp is written by the application through its injectable clock.
-- The migrator splits on semicolons: no semicolon may appear inside a statement or comment.
-- The migrator creates and owns its own bookkeeping table (schema_migrations).

-- ---------------------------------------------------------------- users and auth

CREATE TABLE users (
    id TEXT NOT NULL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'user')),
    is_disabled INTEGER NOT NULL DEFAULT 0 CHECK (is_disabled IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_login_at TEXT
);

-- API keys: only a SHA-256 hash of the full key is kept, the prefix is shown in lists.
-- A key is revoked by setting revoked_at, rows are never reused.
CREATE TABLE api_keys (
    id TEXT NOT NULL PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    prefix TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    last_used_ip TEXT,
    revoked_at TEXT
);

CREATE INDEX ix_api_keys_user ON api_keys (user_id);

-- Append-only. detail is a JSON document stored as plain TEXT (never queried with JSON functions).
CREATE TABLE audit_log (
    id TEXT NOT NULL PRIMARY KEY,
    occurred_at TEXT NOT NULL,
    actor_user_id TEXT REFERENCES users (id) ON DELETE SET NULL,
    actor_ip TEXT,
    action TEXT NOT NULL,
    target_type TEXT,
    target_id TEXT,
    detail TEXT
);

CREATE INDEX ix_audit_log_occurred ON audit_log (occurred_at);
CREATE INDEX ix_audit_log_actor ON audit_log (actor_user_id, occurred_at);

-- ---------------------------------------------------------------- library

-- *_norm columns hold a lowercased, accent-folded copy computed by the application,
-- used for portable LIKE searches and sorting.
CREATE TABLE artists (
    id TEXT NOT NULL PRIMARY KEY,
    name TEXT NOT NULL,
    name_norm TEXT NOT NULL,
    sort_name TEXT,
    musicbrainz_id TEXT UNIQUE,
    yt_channel_id TEXT UNIQUE,
    image_path TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX ix_artists_name_norm ON artists (name_norm);

CREATE TABLE albums (
    id TEXT NOT NULL PRIMARY KEY,
    artist_id TEXT NOT NULL REFERENCES artists (id) ON DELETE RESTRICT,
    name TEXT NOT NULL,
    name_norm TEXT NOT NULL,
    sort_name TEXT,
    year INTEGER,
    genre TEXT,
    release_type TEXT,
    total_tracks INTEGER,
    total_discs INTEGER,
    musicbrainz_release_id TEXT UNIQUE,
    musicbrainz_release_group_id TEXT,
    yt_browse_id TEXT UNIQUE,
    cover_path TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX ix_albums_artist ON albums (artist_id);
CREATE INDEX ix_albums_name_norm ON albums (name_norm);
CREATE INDEX ix_albums_created ON albums (created_at);
CREATE INDEX ix_albums_year ON albums (year);

-- A track row exists from the moment an external video is first requested (status pending),
-- so stars, playlists and history can reference it. artist_id, album_id, path and the file
-- columns are filled when the worker registers the archived file (status ready).
-- artist_name and album_name are the display values, also while pending.
CREATE TABLE tracks (
    id TEXT NOT NULL PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('pending', 'ready', 'failed')),
    title TEXT NOT NULL,
    title_norm TEXT NOT NULL,
    sort_title TEXT,
    artist_id TEXT REFERENCES artists (id) ON DELETE RESTRICT,
    album_id TEXT REFERENCES albums (id) ON DELETE RESTRICT,
    artist_name TEXT NOT NULL,
    album_name TEXT,
    track_number INTEGER,
    disc_number INTEGER,
    year INTEGER,
    genre TEXT,
    duration_ms BIGINT,
    path TEXT UNIQUE,
    format TEXT CHECK (format IN ('opus', 'm4a', 'mp3', 'flac', 'ogg')),
    content_type TEXT,
    size_bytes BIGINT,
    bit_rate_kbps INTEGER,
    sample_rate_hz INTEGER,
    channels INTEGER,
    rg_track_gain_db DOUBLE PRECISION,
    rg_track_peak DOUBLE PRECISION,
    rg_album_gain_db DOUBLE PRECISION,
    rg_album_peak DOUBLE PRECISION,
    needs_review INTEGER NOT NULL DEFAULT 0 CHECK (needs_review IN (0, 1)),
    musicbrainz_recording_id TEXT,
    musicbrainz_track_id TEXT,
    isrc TEXT,
    yt_video_id TEXT UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived_at TEXT
);

CREATE INDEX ix_tracks_album ON tracks (album_id, disc_number, track_number);
CREATE INDEX ix_tracks_artist ON tracks (artist_id);
CREATE INDEX ix_tracks_status ON tracks (status);
CREATE INDEX ix_tracks_title_norm ON tracks (title_norm);
CREATE INDEX ix_tracks_needs_review ON tracks (needs_review);
CREATE INDEX ix_tracks_created ON tracks (created_at);

-- Virtual ids that resolve to a library track (contracts/ids.md), e.g. 'yt:dQw4w9WgXcQ'.
-- Kept forever, several aliases may point to the same track.
CREATE TABLE track_aliases (
    alias TEXT NOT NULL PRIMARY KEY,
    track_id TEXT NOT NULL REFERENCES tracks (id) ON DELETE CASCADE,
    created_at TEXT NOT NULL
);

CREATE INDEX ix_track_aliases_track ON track_aliases (track_id);

-- ---------------------------------------------------------------- jobs (download queue)

-- One job row per (kind, track): a retry reuses the row, which also deduplicates requests
-- per video id. Claimed with a lease (internal-worker.yaml), an expired lease goes back to
-- queued. priority: higher first (stream 100, prefetch 50, keep 30, import 10).
CREATE TABLE jobs (
    id TEXT NOT NULL PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('download')),
    track_id TEXT NOT NULL REFERENCES tracks (id) ON DELETE CASCADE,
    yt_video_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('queued', 'downloading', 'tagging', 'ready', 'failed', 'cancelled')),
    priority INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    not_before TEXT,
    lease_id TEXT UNIQUE,
    lease_owner TEXT,
    lease_expires_at TEXT,
    progress DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (progress >= 0 AND progress <= 1),
    bytes_downloaded BIGINT,
    bytes_total BIGINT,
    staging_path TEXT,
    error_code TEXT,
    error_message TEXT,
    requested_by TEXT REFERENCES users (id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    UNIQUE (kind, track_id)
);

CREATE INDEX ix_jobs_claim ON jobs (state, priority, created_at);
CREATE INDEX ix_jobs_lease_expiry ON jobs (state, lease_expires_at);
CREATE INDEX ix_jobs_video ON jobs (yt_video_id);

-- Last report of each worker process (yt-dlp version, canary), shown in the admin panel.
CREATE TABLE worker_status (
    worker_id TEXT NOT NULL PRIMARY KEY,
    version TEXT,
    ytdlp_version TEXT,
    last_seen_at TEXT NOT NULL,
    canary_at TEXT,
    canary_ok INTEGER CHECK (canary_ok IN (0, 1)),
    canary_message TEXT
);

-- ---------------------------------------------------------------- per-user state

CREATE TABLE playlists (
    id TEXT NOT NULL PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    comment TEXT,
    is_public INTEGER NOT NULL DEFAULT 0 CHECK (is_public IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX ix_playlists_owner ON playlists (owner_id);

-- position is 0-based and dense, renumbered by the application on removal.
CREATE TABLE playlist_tracks (
    playlist_id TEXT NOT NULL REFERENCES playlists (id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    track_id TEXT NOT NULL REFERENCES tracks (id) ON DELETE CASCADE,
    added_at TEXT NOT NULL,
    PRIMARY KEY (playlist_id, position)
);

CREATE INDEX ix_playlist_tracks_track ON playlist_tracks (track_id);

CREATE TABLE starred_tracks (
    user_id TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    track_id TEXT NOT NULL REFERENCES tracks (id) ON DELETE CASCADE,
    starred_at TEXT NOT NULL,
    PRIMARY KEY (user_id, track_id)
);

CREATE TABLE starred_albums (
    user_id TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    album_id TEXT NOT NULL REFERENCES albums (id) ON DELETE CASCADE,
    starred_at TEXT NOT NULL,
    PRIMARY KEY (user_id, album_id)
);

CREATE TABLE starred_artists (
    user_id TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    artist_id TEXT NOT NULL REFERENCES artists (id) ON DELETE CASCADE,
    starred_at TEXT NOT NULL,
    PRIMARY KEY (user_id, artist_id)
);

-- scrobble: submission 1 = played, 0 = now playing notification.
CREATE TABLE play_history (
    id TEXT NOT NULL PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    track_id TEXT NOT NULL REFERENCES tracks (id) ON DELETE CASCADE,
    played_at TEXT NOT NULL,
    submission INTEGER NOT NULL DEFAULT 1 CHECK (submission IN (0, 1)),
    client TEXT
);

CREATE INDEX ix_play_history_user ON play_history (user_id, played_at);
CREATE INDEX ix_play_history_track ON play_history (track_id);

-- Aggregate kept in step with play_history (playCount, played, most played).
CREATE TABLE user_track_stats (
    user_id TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    track_id TEXT NOT NULL REFERENCES tracks (id) ON DELETE CASCADE,
    play_count BIGINT NOT NULL DEFAULT 0,
    last_played_at TEXT,
    PRIMARY KEY (user_id, track_id)
);

CREATE INDEX ix_user_track_stats_count ON user_track_stats (user_id, play_count);

-- One saved queue per user (OpenSubsonic savePlayQueue). Entries keep the raw item id
-- (library UUID or yt: id) and are resolved when read, so saving a queue never triggers downloads.
CREATE TABLE play_queues (
    user_id TEXT NOT NULL PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
    current_item_id TEXT,
    position_ms BIGINT NOT NULL DEFAULT 0,
    changed_at TEXT NOT NULL,
    changed_by TEXT NOT NULL
);

CREATE TABLE play_queue_entries (
    user_id TEXT NOT NULL REFERENCES play_queues (user_id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    item_id TEXT NOT NULL,
    PRIMARY KEY (user_id, idx)
);

-- ---------------------------------------------------------------- lyrics

-- One row per track. not_found = 1 is a negative cache entry, retried after retry_after.
CREATE TABLE lyrics (
    track_id TEXT NOT NULL PRIMARY KEY REFERENCES tracks (id) ON DELETE CASCADE,
    source TEXT NOT NULL CHECK (source IN ('lrclib', 'tags')),
    source_ref TEXT,
    lang TEXT NOT NULL DEFAULT 'und',
    synced_lrc TEXT,
    plain_text TEXT,
    offset_ms INTEGER NOT NULL DEFAULT 0,
    not_found INTEGER NOT NULL DEFAULT 0 CHECK (not_found IN (0, 1)),
    fetched_at TEXT NOT NULL,
    retry_after TEXT
);

-- ---------------------------------------------------------------- imports

CREATE TABLE imports (
    id TEXT NOT NULL PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    source TEXT NOT NULL CHECK (source IN ('ytmusic', 'csv', 'exportify_csv', 'spotify_json')),
    -- URL and playlist id only for `ytmusic`; file imports (SPEC §11, T03d) have neither.
    source_url TEXT,
    source_playlist_id TEXT,
    name TEXT,
    state TEXT NOT NULL CHECK (state IN ('queued', 'reading', 'matching', 'done', 'failed')),
    total_items INTEGER NOT NULL DEFAULT 0,
    matched_items INTEGER NOT NULL DEFAULT 0,
    not_found_items INTEGER NOT NULL DEFAULT 0,
    playlist_id TEXT REFERENCES playlists (id) ON DELETE SET NULL,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE INDEX ix_imports_user ON imports (user_id, created_at);

CREATE TABLE import_items (
    import_id TEXT NOT NULL REFERENCES imports (id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    source_ref TEXT,
    source_title TEXT NOT NULL,
    source_artist TEXT,
    source_album TEXT,
    source_duration_ms BIGINT,
    source_isrc TEXT,
    state TEXT NOT NULL CHECK (state IN ('pending', 'matched', 'not_found', 'failed')),
    match_score DOUBLE PRECISION CHECK (match_score >= 0 AND match_score <= 1),
    yt_video_id TEXT,
    track_id TEXT REFERENCES tracks (id) ON DELETE SET NULL,
    error_message TEXT,
    PRIMARY KEY (import_id, position)
);

-- ---------------------------------------------------------------- settings and shared state

-- Runtime settings edited in the admin panel (never secrets: those come from env vars).
CREATE TABLE settings (
    key TEXT NOT NULL PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Disk-backed TtlCache (search results, catalog lookups). value is application-encoded TEXT.
-- Expired rows are ignored on read and purged periodically.
CREATE TABLE cache_entries (
    key TEXT NOT NULL PRIMARY KEY,
    value TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX ix_cache_entries_expires ON cache_entries (expires_at);

-- RateLimiter state: one token bucket per key (e.g. 'auth:ip:192.0.2.10', 'auth:key:<key id>')
-- plus the consecutive failure counter that drives temporary lockout.
CREATE TABLE rate_limit_buckets (
    key TEXT NOT NULL PRIMARY KEY,
    tokens DOUBLE PRECISION NOT NULL,
    updated_at TEXT NOT NULL,
    failures INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT
);

CREATE INDEX ix_rate_limit_buckets_updated ON rate_limit_buckets (updated_at);
