-- SPDX-FileCopyrightText: 2026 UltimateTunes contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- 0300_jobs_attempt_history (PLAN T08): staging sequence, what a retry is compared with, lease length.
--
-- attempt_seq: per-job sequence of claims. Every claim increments it and it never resets, so the
-- staging directory <job id>/<attempt_seq> is unique for the life of the job, even after a new
-- request re-queues a failed job and resets its retry budget (attempts).
-- A claim starts a new attempt and clears the streaming columns of the previous one
-- (expected_size, format_id, ...). The api still needs the last reported format and exact size
-- to tell whether a retry produces the same bytes (contracts/openapi/internal-worker.yaml:
-- a retry with another formatId or expectedSize aborts the open streams). The claim copies
-- them here when the previous attempt reported a format, so an attempt that died before its
-- first progress report does not erase them.
-- previous_format_id: formatId of the last attempt that reported one (NULL before any report).
-- previous_expected_size: expectedSize reported by that same attempt (NULL when it never
-- learned the exact size).
-- lease_seconds: lease length asked for at claim; progress reports extend the lease by it.
ALTER TABLE jobs ADD COLUMN attempt_seq INTEGER NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN previous_format_id TEXT;
ALTER TABLE jobs ADD COLUMN previous_expected_size BIGINT;
ALTER TABLE jobs ADD COLUMN lease_seconds INTEGER;
