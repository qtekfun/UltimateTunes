-- SPDX-FileCopyrightText: 2026 UltimateTunes contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- Abuse limits (fix/abuse-limits). Before queuing a download the api counts the caller's queued
-- or running jobs (`jobs.requested_by`, this index), and it charges every downloaded byte to
-- the user who requested the job at that moment, in one row per user and UTC hour
-- (`download_usage`). The bytes of the last 24 hours bound new requests and claims. Rows never
-- move to another user, and a retried attempt adds to them instead of starting again.
CREATE INDEX ix_jobs_requested_by ON jobs (requested_by, state);

CREATE TABLE download_usage (
    user_id TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    hour_start TEXT NOT NULL,
    bytes BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, hour_start)
);
