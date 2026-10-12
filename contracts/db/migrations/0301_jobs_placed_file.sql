-- SPDX-FileCopyrightText: 2026 UltimateTunes contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- The archive file a job reserved and may have moved into /music (registerTrack): its path
-- under /music and the SHA-256 it was registered with, updated when the worker reports its own
-- track's ReplayGain (album gain rewrites the file before the move). Unlike library_path they
-- survive a release, so a retry can adopt the file an attempt moved before dying, or remove it
-- when the retry merges into another track or picks another path (SPEC section 11).
ALTER TABLE jobs ADD COLUMN placed_path TEXT;
ALTER TABLE jobs ADD COLUMN placed_sha256 TEXT;
