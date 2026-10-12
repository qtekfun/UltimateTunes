# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Database access, owned by the coordinator (PLAN T02); streams add repositories in their own
packages on top of it.

- `driver`: `Connection` over SQLite (v1) and PostgreSQL (dev-only until PLAN T25), portable
  `?` placeholders, translated `DatabaseError` / `IntegrityError`.
- `database`: `Database`, one serialized writer plus a pool of readers, opened lazily.
- `repository`: `Repository` base and typed row mapping (`from_row`).
- `migrate`: the migrator behind `ultimatetunes migrate`.
"""

from ultimatetunes.db.database import Database
from ultimatetunes.db.driver import Connection, DatabaseError, IntegrityError
from ultimatetunes.db.repository import Repository, from_row

__all__ = ["Connection", "Database", "DatabaseError", "IntegrityError", "Repository", "from_row"]
