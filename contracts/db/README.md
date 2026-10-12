<!--
SPDX-FileCopyrightText: 2026 UltimateTunes contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Database migrations

Plain SQL files applied in order by `ultimatetunes migrate` (our own small migrator, no ORM). CI applies every migration to an empty **SQLite** database and to an empty **PostgreSQL 17** database; both must succeed. Only SQLite ships in v1. PostgreSQL arrives in PLAN phase 5, and these rules keep that switch a configuration change.

## Rules

1. **One file per change**, named `NNNN_snake_case.sql` (four digits, then a short description), e.g. `0102_api_key_scopes.sql`. The number sets the order.
2. **Never edit a migration that has been merged.** To fix one, add a new migration. The migrator records applied versions in its own table, `schema_migrations`, which it creates itself. No migration creates or touches that table.
3. **Stay inside your stream's number range** (below). Take the next free number in your range. Two streams can never collide.
4. **SPDX header** as `--` comments at the top of the file.
5. **Portable SQL only.** Everything must run unchanged on SQLite (3.40+) and PostgreSQL (16+):
   - Ids: `TEXT` (UUIDv7 as text, see `../ids.md`). No `INTEGER PRIMARY KEY` rowid aliases, no `AUTOINCREMENT`, no `SERIAL`/`IDENTITY`.
   - Integers: `INTEGER`, or `BIGINT` for sizes, durations and counters that can grow. Both get INTEGER affinity on SQLite.
   - Fractions: `DOUBLE PRECISION`, which gets REAL affinity on SQLite. Do not use `REAL` (it is 4 bytes on PostgreSQL) or `NUMERIC`.
   - Booleans: `INTEGER NOT NULL DEFAULT 0 CHECK (col IN (0, 1))`. No `BOOLEAN`, no `TRUE`/`FALSE` literals.
   - Timestamps: `TEXT` in UTC, fixed width `YYYY-MM-DDTHH:MM:SS.mmmZ` (e.g. `2026-10-12T08:15:30.123Z`), so text comparison and `ORDER BY` follow time order. The application writes every timestamp through its injectable clock. Do not use `DEFAULT CURRENT_TIMESTAMP`, `now()`, `datetime()` or `TIMESTAMP` columns.
   - JSON documents are stored as plain `TEXT` and never queried with JSON functions.
   - Defaults are literal constants only.
   - Foreign keys are declared inline with an explicit `ON DELETE` action (`CASCADE`, `SET NULL` or `RESTRICT`). The SQLite driver turns on `PRAGMA foreign_keys = ON` for every connection.
   - Indexes: plain `CREATE INDEX` / `CREATE UNIQUE INDEX`. No partial indexes (`WHERE`), no expression indexes, no `IF NOT EXISTS`, no `COLLATE` clauses. A nullable `UNIQUE` column is fine: both databases allow many NULLs.
   - Schema changes: `CREATE TABLE`, `CREATE INDEX`, `DROP INDEX`, `ALTER TABLE … ADD COLUMN` (nullable or with a constant default). Anything else, such as changing or dropping a column, is a new table plus a data copy plus a rename, and needs the coordinator to sign off.
   - Avoid reserved words as names (`user`, `order`, `offset`, `key` is fine, `value` is fine). When in doubt, add a suffix (`offset_ms`).
   - No `PRAGMA`, no `BEGIN`/`COMMIT` (the migrator wraps each file in a transaction), no `VACUUM`, no triggers, no views in v1.
6. **Statement layout: the migrator splits each file on a `;` that ends a line.** So:
   - every statement ends with `;` as the **last character of a line** (trailing spaces are fine);
   - **no line inside a statement ends with `;`** (not in a string literal, not in a `CHECK`, nowhere);
   - a `;` in the middle of a line (e.g. `DEFAULT ';'`) is left alone, but avoid it anyway.
   `server/tests/test_migrate.py` checks every file in this directory against these rules.
7. **`--` comments only, each on its own line** (the migrator drops whole-line `--` comments before splitting). No trailing comments after SQL on the same line and no `/* */` blocks.
8. Check locally before pushing:
   ```sh
   sqlite3 :memory: < contracts/db/migrations/NNNN_x.sql
   docker run --rm -d --name ut-pg -e POSTGRES_PASSWORD=ci -p 55433:5432 postgres:17
   docker exec -i ut-pg psql -U postgres -v ON_ERROR_STOP=1 < contracts/db/migrations/0001_init.sql
   docker exec -i ut-pg psql -U postgres -v ON_ERROR_STOP=1 < contracts/db/migrations/NNNN_x.sql
   docker stop ut-pg
   ```

## Number ranges

| Range | Owner | Area |
| --- | --- | --- |
| `0001`–`0099` | Coordinator (stream A) | Initial schema, cross-cutting changes, `contracts/<topic>` PRs |
| `0100`–`0199` | Stream B (T04, T05) | Users, API keys, auth, rate limit, audit, library and browsing |
| `0200`–`0299` | Stream C (T06, T07) | Search, id resolution, radio |
| `0300`–`0399` | Stream D (T08, T09) | Jobs, worker, tagging, archive |
| `0400`–`0499` | Stream H (T10, T11) | Lyrics, playlist imports |
| `0500`–`0599` | Stream L (T15) | Admin panel |
| `0600`–`0699` | Stream E (T16) | Streaming while downloading |
| `0700`–`9999` | Coordinator | Reserved |

Migrations from different ranges are applied in plain numeric order. A stream migration may only depend on `0001`–`0099` and on its own earlier migrations, never on another stream's range. If you need that, ask the coordinator.

## Tables in `0001_init.sql`

| Table | Purpose | Main users |
| --- | --- | --- |
| `users`, `api_keys`, `audit_log` | Accounts (Argon2id), per-device keys (SHA-256 hash, prefix, last use, revocation), audit trail | T04, T15 |
| `rate_limit_buckets` | `RateLimiter` SQLite implementation: token bucket, failure count, lockout | T04 |
| `artists`, `albums`, `tracks` | Library. A track row exists from its first request (`status` `pending` → `ready` / `failed`) | T05, T09, T16 |
| `track_aliases` | Virtual ids (`yt:…`) → library track id | T06, T16 |
| `jobs`, `worker_status` | Download queue with leases. Worker reports (yt-dlp version, canary) | T08, T15 |
| `playlists`, `playlist_tracks` | User playlists (also the result of imports) | T05, T11 |
| `starred_tracks`, `starred_albums`, `starred_artists` | Favourites | T05 |
| `play_history`, `user_track_stats` | Scrobbles and per-user play counts (Listen Now, most played) | T05, T07 |
| `play_queues`, `play_queue_entries` | Saved play queue per user (raw item ids) | T05 |
| `lyrics` | LRCLIB results, including negative cache | T10 |
| `imports`, `import_items` | Playlist imports and match report | T11 |
| `settings` | Admin-editable runtime settings (no secrets) | T15 |
| `cache_entries` | `TtlCache` SQLite implementation (disk-backed to keep RAM low) | T06 |
