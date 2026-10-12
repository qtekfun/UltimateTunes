-- SPDX-FileCopyrightText: 2026 UltimateTunes contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- 0300_jobs_attempt_history (PLAN T08): what a retry must be compared with, and the lease length.
--
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
ALTER TABLE jobs ADD COLUMN previous_format_id TEXT;
ALTER TABLE jobs ADD COLUMN previous_expected_size BIGINT;
ALTER TABLE jobs ADD COLUMN lease_seconds INTEGER;
