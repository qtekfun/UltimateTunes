-- SPDX-FileCopyrightText: 2026 UltimateTunes contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
-- Optional TOTP two-factor authentication on the password logins (feat/totp-2fa).
-- The shared secret is stored (reversible-sensitive; see SECURITY.md: protect /data).
-- Recovery codes are stored only as Argon2id hashes, never in clear.
CREATE TABLE user_totp (
    user_id TEXT PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
    secret TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
    last_step BIGINT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    confirmed_at TEXT
);
CREATE TABLE totp_recovery_codes (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    code_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    used_at TEXT
);
CREATE INDEX idx_totp_recovery_user ON totp_recovery_codes (user_id);
