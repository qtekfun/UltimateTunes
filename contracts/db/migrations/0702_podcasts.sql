-- SPDX-FileCopyrightText: 2026 UltimateTunes contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- 0702_podcasts (PLAN T41): podcast shows, episodes, follows and progress (docs/podcasts.md).
-- Episodes are not tracks: nothing here refers to the music tables.
--
-- podcast_shows.source: 'youtube' in phase 1. No CHECK, so phase 2 needs no table rebuild.
-- podcast_shows.yt_playlist_id: the show id of YouTube Music without its MPSP prefix.
CREATE TABLE podcast_shows (
    id TEXT NOT NULL PRIMARY KEY,
    source TEXT NOT NULL,
    yt_playlist_id TEXT UNIQUE,
    title TEXT NOT NULL,
    author TEXT,
    description TEXT,
    yt_thumbnail_url TEXT,
    refreshed_at TEXT,
    next_refresh_at TEXT,
    refresh_failures INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX ix_podcast_shows_refresh ON podcast_shows (next_refresh_at);

-- list_seq: order of the show's list, larger is newer (the upstream order is kept, dates are not
-- reliable). Newly published episodes get numbers above the maximum, back catalogue below the
-- minimum. published_at and duration_ms stay NULL until known.
-- state: the file on the server. path is relative to the library root, under .podcasts/.
-- discovered_at: when the server first saw the episode.
CREATE TABLE podcast_episodes (
    id TEXT NOT NULL PRIMARY KEY,
    show_id TEXT NOT NULL REFERENCES podcast_shows (id) ON DELETE CASCADE,
    yt_video_id TEXT UNIQUE,
    title TEXT NOT NULL,
    description TEXT,
    list_seq BIGINT NOT NULL,
    published_at TEXT,
    duration_ms BIGINT,
    yt_thumbnail_url TEXT,
    state TEXT NOT NULL CHECK (state IN ('remote', 'downloading', 'ready', 'failed')),
    path TEXT UNIQUE,
    content_type TEXT,
    size_bytes BIGINT,
    error_code TEXT,
    downloaded_at TEXT,
    discovered_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX ix_podcast_episodes_show ON podcast_episodes (show_id, list_seq);
CREATE INDEX ix_podcast_episodes_state ON podcast_episodes (state, downloaded_at);
CREATE INDEX ix_podcast_episodes_new ON podcast_episodes (discovered_at);

CREATE TABLE podcast_follows (
    user_id TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    show_id TEXT NOT NULL REFERENCES podcast_shows (id) ON DELETE CASCADE,
    speed DOUBLE PRECISION NOT NULL DEFAULT 1.0 CHECK (speed >= 0.5 AND speed <= 3.0),
    auto_download INTEGER NOT NULL DEFAULT 0 CHECK (auto_download IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, show_id)
);

CREATE INDEX ix_podcast_follows_show ON podcast_follows (show_id);

-- changed_at: when it happened on the client (never later than the server clock), the newest
-- wins. updated_at: when the server stored it, for incremental sync.
CREATE TABLE podcast_progress (
    user_id TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    episode_id TEXT NOT NULL REFERENCES podcast_episodes (id) ON DELETE CASCADE,
    position_ms BIGINT NOT NULL DEFAULT 0 CHECK (position_ms >= 0),
    played INTEGER NOT NULL DEFAULT 0 CHECK (played IN (0, 1)),
    keep_file INTEGER NOT NULL DEFAULT 0 CHECK (keep_file IN (0, 1)),
    changed_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, episode_id)
);

CREATE INDEX ix_podcast_progress_sync ON podcast_progress (user_id, updated_at);
CREATE INDEX ix_podcast_progress_episode ON podcast_progress (episode_id);
