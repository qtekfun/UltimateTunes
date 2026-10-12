-- SPDX-FileCopyrightText: 2026 UltimateTunes contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- PLAN T11: how many times an import run paused on a YouTube Music outage while reading the
-- playlist (imports) or matching an item (import_items). After a few pauses the playlist read
-- or the item fails, so an error that repeats for one query never keeps an import running.
ALTER TABLE imports ADD COLUMN pauses INTEGER NOT NULL DEFAULT 0;
ALTER TABLE import_items ADD COLUMN pauses INTEGER NOT NULL DEFAULT 0;
