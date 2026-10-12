# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Download jobs on the api side. Owned by PLAN T08 (job state machine, 100 % coverage).

T02 ships:
- `queue`: the `JobQueue` protocol and `SqliteJobQueue` on the `jobs` table (enqueue with
  deduplication per track, claim with a lease, heartbeat, release, lease expiry).
- `routes`: `/ut/v1/tracks/{id}/request` and `/ut/v1/tracks/{id}/status` stubs.
- `internal_api`: `/internal/v1/jobs/*` and `/internal/v1/workers/*` stubs.
T08 completes the state machine (progress, tagging, retries with backoff, cancel, track
status) here.
"""
