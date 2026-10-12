-- SPDX-FileCopyrightText: 2026 UltimateTunes contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- Abuse limits (fix/abuse-limits): before queuing a download the api counts the caller's
-- queued or running jobs and sums the bytes of the jobs it requested over the last 24 hours
-- (`jobs.requested_by`, `jobs.updated_at`). This index keeps both lookups to one user's rows.
CREATE INDEX ix_jobs_requested_by ON jobs (requested_by, updated_at);
