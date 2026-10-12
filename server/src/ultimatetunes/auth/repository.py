# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Users, API keys and the audit log (tables of contracts/db/migrations/0001_init.sql)."""

import json
from dataclasses import dataclass, field

from ultimatetunes.db.repository import Repository, to_db_bool

_USER_COLUMNS = (
    "id, username, password_hash, role, is_disabled, created_at, updated_at, last_login_at"
)
_KEY_COLUMNS = "id, user_id, name, prefix, created_at, last_used_at, last_used_ip, revoked_at"


@dataclass(frozen=True)
class User:
    id: str
    username: str
    password_hash: str = field(repr=False)
    role: str
    is_disabled: bool
    created_at: str
    updated_at: str
    last_login_at: str | None


@dataclass(frozen=True)
class ApiKey:
    id: str
    user_id: str
    name: str
    prefix: str
    created_at: str
    last_used_at: str | None
    last_used_ip: str | None
    revoked_at: str | None


@dataclass(frozen=True)
class KeyOwner:
    """An API key found by its hash, with the user it belongs to."""

    key_id: str
    revoked_at: str | None
    last_used_at: str | None
    last_used_ip: str | None
    user_id: str
    username: str
    role: str
    is_disabled: bool


@dataclass(frozen=True)
class AuditEntry:
    id: str
    occurred_at: str
    actor_user_id: str | None
    actor_ip: str | None
    action: str
    target_type: str | None
    target_id: str | None
    detail: str | None


class UserRepository(Repository):
    def get(self, user_id: str) -> User | None:
        return self.one(
            User,
            "SELECT id, username, password_hash, role, is_disabled, created_at, updated_at,"
            " last_login_at"
            " FROM users WHERE id = ?",
            (user_id,),
        )

    def by_username(self, username: str) -> User | None:
        return self.one(
            User,
            "SELECT id, username, password_hash, role, is_disabled, created_at, updated_at,"
            " last_login_at"
            " FROM users WHERE username = ?",
            (username,),
        )

    def all_users(self) -> list[User]:
        return self.all(
            User,
            "SELECT id, username, password_hash, role, is_disabled, created_at, updated_at,"
            " last_login_at"
            " FROM users ORDER BY username",
        )

    def count(self) -> int:
        return int(str(self.conn.execute("SELECT COUNT(*) FROM users").scalar()))

    def insert(self, user: User) -> None:
        self.run(
            "INSERT INTO users (id, username, password_hash, role, is_disabled, created_at,"
            " updated_at, last_login_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user.id,
                user.username,
                user.password_hash,
                user.role,
                to_db_bool(user.is_disabled),
                user.created_at,
                user.updated_at,
                user.last_login_at,
            ),
        )

    def set_password_hash(self, user_id: str, password_hash: str, now: str) -> int:
        return self.run(
            "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
            (password_hash, now, user_id),
        )

    def set_disabled(self, user_id: str, disabled: bool, now: str) -> int:
        return self.run(
            "UPDATE users SET is_disabled = ?, updated_at = ? WHERE id = ?",
            (to_db_bool(disabled), now, user_id),
        )

    def set_role(self, user_id: str, role: str, now: str) -> int:
        return self.run(
            "UPDATE users SET role = ?, updated_at = ? WHERE id = ?", (role, now, user_id)
        )

    def touch_login(self, user_id: str, now: str) -> None:
        self.run("UPDATE users SET last_login_at = ? WHERE id = ?", (now, user_id))


class ApiKeyRepository(Repository):
    def insert(self, key: ApiKey, key_hash: str) -> None:
        self.run(
            "INSERT INTO api_keys (id, user_id, name, prefix, created_at, last_used_at,"
            " last_used_ip, revoked_at, key_hash)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                key.id,
                key.user_id,
                key.name,
                key.prefix,
                key.created_at,
                key.last_used_at,
                key.last_used_ip,
                key.revoked_at,
                key_hash,
            ),
        )

    def get(self, key_id: str) -> ApiKey | None:
        return self.one(
            ApiKey,
            "SELECT id, user_id, name, prefix, created_at, last_used_at, last_used_ip, revoked_at"
            " FROM api_keys WHERE id = ?",
            (key_id,),
        )

    def of_user(self, user_id: str) -> list[ApiKey]:
        """Newest first (UUIDv7 ids break ties of the same millisecond), revoked included."""
        return self.all(
            ApiKey,
            "SELECT id, user_id, name, prefix, created_at, last_used_at, last_used_ip, revoked_at"
            " FROM api_keys WHERE user_id = ?"
            " ORDER BY created_at DESC, id DESC",
            (user_id,),
        )

    def owner_by_hash(self, key_hash: str) -> KeyOwner | None:
        return self.one(
            KeyOwner,
            "SELECT k.id AS key_id, k.revoked_at, k.last_used_at, k.last_used_ip,"
            " u.id AS user_id, u.username, u.role, u.is_disabled"
            " FROM api_keys k JOIN users u ON u.id = k.user_id WHERE k.key_hash = ?",
            (key_hash,),
        )

    def revoke(self, key_id: str, now: str) -> int:
        """Sets `revoked_at` once; revoking again changes nothing."""
        return self.run(
            "UPDATE api_keys SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
            (now, key_id),
        )

    def revoke_all(self, user_id: str, now: str) -> int:
        """Revokes every live key of the user; how many."""
        return self.run(
            "UPDATE api_keys SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
            (now, user_id),
        )

    def touch(self, key_id: str, now: str, ip: str | None) -> None:
        self.run(
            "UPDATE api_keys SET last_used_at = ?, last_used_ip = ? WHERE id = ?",
            (now, ip, key_id),
        )


class AuditRepository(Repository):
    """Append-only. `detail` is a small JSON document that never holds a secret."""

    def add(self, entry: AuditEntry) -> None:
        self.run(
            "INSERT INTO audit_log (id, occurred_at, actor_user_id, actor_ip, action,"
            " target_type, target_id, detail) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                entry.id,
                entry.occurred_at,
                entry.actor_user_id,
                entry.actor_ip,
                entry.action,
                entry.target_type,
                entry.target_id,
                entry.detail,
            ),
        )

    def recent(self, limit: int) -> list[AuditEntry]:
        return self.all(
            AuditEntry,
            "SELECT id, occurred_at, actor_user_id, actor_ip, action, target_type, target_id,"
            " detail FROM audit_log ORDER BY occurred_at DESC, id DESC LIMIT ?",
            (limit,),
        )


def audit_detail(values: dict[str, object] | None) -> str | None:
    return None if not values else json.dumps(values, ensure_ascii=False, sort_keys=True)


class SessionEpochRepository(Repository):
    """The per-user session epochs of the admin panel and the web player (rows of `settings`,
    `admin.session_epoch.<user id>` and `web.session_epoch.<user id>`). Each is part of every
    session cookie's fingerprint: raising it ends every session of that user at once."""

    def get(self, key: str) -> int:
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        try:
            return int(str(row["value"])) if row is not None else 0
        except ValueError:
            return 0

    def bump(self, key: str, now: str) -> int:
        """The epoch plus one, stored (in the caller's transaction)."""
        epoch = self.get(key) + 1
        if not self.run(
            "UPDATE settings SET value = ?, updated_at = ? WHERE key = ?", (str(epoch), now, key)
        ):
            self.run(
                "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                (key, str(epoch), now),
            )
        return epoch
