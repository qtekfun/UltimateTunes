-- SPDX-FileCopyrightText: 2026 UltimateTunes contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- Admin panel lists (feat/admin-polish): the audit log filtered by action, newest first, and
-- the download queue unfiltered, newest first (`ORDER BY updated_at DESC`, paged).
CREATE INDEX ix_audit_log_action ON audit_log (action, occurred_at);
CREATE INDEX ix_jobs_updated ON jobs (updated_at);
