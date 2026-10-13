<!--
SPDX-FileCopyrightText: 2026 UltimateTunes contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Two-factor authentication (TOTP)

UltimateTunes supports an **optional** time-based one-time password (TOTP, RFC 6238) as a second
factor on the **password logins**. It works with any standard authenticator app (Aegis, FreeOTP,
Google Authenticator, 1Password, …) and needs no extra server dependency: the codes are computed
with the Python standard library (`server/src/ultimatetunes/auth/totp.py`), and the enrollment QR
code reuses the admin panel's own QR generator.

## What it protects, and what it does not

Three surfaces sign in with a **password** and are covered:

- the **admin panel** login (`/admin/login`),
- the **web player** login (`POST /web/login`),
- **`POST /ut/v1/keys`** (password → a new device API key).

**API-key authentication is never a second factor.** The Android app and any OpenSubsonic client
authenticate with a per-device API key (a 256-bit token, already something you have). A code is
never asked for on `/rest` or on the authenticated `/ut/v1` routes, so existing devices keep
working unchanged after 2FA is turned on. 2FA only guards the *password* step, i.e. signing in to a
browser and enrolling a **new** device.

## Enrolling

1. Open **Two-factor** in the admin panel (`/admin/2fa`), or **Settings → Two-factor
   authentication** in the web player.
2. Select **Set up**. The server shows a QR code and the secret in text. Scan it with your
   authenticator app, or type the secret.
3. Enter the 6-digit code the app shows to **confirm**. Only a correct code turns the factor on,
   which proves the secret was stored correctly.
4. The server then shows **ten one-time recovery codes**. Save them now — they are shown only once.

From then on, after the password is accepted the login asks for a code (the second step). A
**recovery code** is accepted in place of a TOTP code and is spent on use (each works once). When
you run low, generate a new set from the settings page (it replaces the remaining codes). Turning
the factor off, and generating new recovery codes, both re-ask for your current password.

## Requiring 2FA (operator policy)

`UT_AUTH_REQUIRE_2FA` (see `docs/configuration.md`) lets the server operator require a second
factor:

- `off` (default) — nobody is forced; any user may still enable it for themselves.
- `admins` — every admin must use it.
- `all` — every account must use it.

A covered user who has not enrolled yet gets **no usable session**: after the password step they
are redirected to the setup page (the admin panel's **Two-factor** page, the web player's
**Settings**) and every other route is refused until they enroll — only enrollment, the 2FA setup
actions and signing out are reachable. Once a covered user has enrolled, they cannot turn the
factor off. The policy is an environment variable, so it is part of the deployment, not something
a single admin session can switch.

## Brute force and replay

- The password lockout/back-off (per IP and per username, SECURITY.md) runs **in front** of the
  second step unchanged.
- The second step has its **own** lockout bucket (`auth:2fa:<user id>`): repeated wrong codes lock
  that user's second step for `UT_AUTH_LOCKOUT_S` after `UT_AUTH_MAX_FAILURES_PER_USER` tries.
- A code is accepted within `UT_AUTH_2FA_WINDOW` (default ±1) 30 s steps for clock drift. A code
  is **strictly single-use**: accepting it advances the stored time step with one atomic
  conditional `UPDATE` (`WHERE last_step < step`), so even two requests presenting the same valid
  code at the same moment cannot both succeed — at most one wins (RFC 6238 §5.2).
- The shared secret and the recovery codes never appear in logs, the audit log or an error. Every
  outcome is an `auth.2fa` security event with the user id and a reason, never a code.

## Secret at rest — encrypted

The TOTP shared secret **must be reversible** (the server recomputes codes from it), so it cannot
be a hash. It is **encrypted at rest** with **`cryptography.fernet.Fernet`** (AES-128-CBC +
HMAC-SHA256; `cryptography`, Apache-2.0 OR BSD-3-Clause) under a key the operator supplies out of
band, so the database alone is not enough to read the secrets. Recovery codes are stored only as
Argon2id hashes and spent once.

### The key

Set **`UT_TOTP_ENCRYPTION_KEY`** to a urlsafe-base64 32-byte Fernet key, from an environment
variable or the Docker secret `ut_totp_encryption_key`. Generate one with:

```sh
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

- **2FA needs the key.** Without it, enrollment and the login second step **fail closed** with a
  clear operator error — the server never falls back to storing or accepting a plaintext secret.
- **Protect the key as well as the database.** Keep it where you keep `UT_ADMIN_SESSION_SECRET`
  (an env var or a Docker secret, never in the repo or `.env`). If an attacker has *both* the
  database and the key, they can read the secrets; either one alone is not enough.
- **If the key is lost**, enrolled TOTP secrets become unreadable. Affected users sign in with a
  **recovery code** (recovery codes do not use this key) and re-enroll; set a new key first.

### Key rotation (optional, proposed)

Rotation is not implemented. The clean way to add it later is **`cryptography.fernet.MultiFernet`**:
`UT_TOTP_ENCRYPTION_KEY` becomes a comma-separated list (new key first for encryption, old keys
still accepted for decryption), and a one-off `ultimatetunes rotate-totp-keys` command re-encrypts
every `user_totp.secret` with the first key. Until then, rotating the key means asking enrolled
users to re-enroll (or restoring the old key).

## `POST /ut/v1/keys` and the app — `totp` field

`CreateKeyRequest` carries an **optional** `totp` field (`contracts/openapi/ut-v1.yaml`, added by
the coordinator with this change). When the account has 2FA enabled, the server requires a valid
code (a TOTP code or a recovery code) in addition to the password, so a stolen password alone
cannot enroll a new device. The field is optional and consulted only for 2FA-enabled accounts, so
it is backward-compatible: clients that do not send it keep creating keys for accounts without a
second factor.

```yaml
    CreateKeyRequest:
      properties:
        username: { type: string, minLength: 1, maxLength: 64 }
        password: { type: string, minLength: 1, maxLength: 1024 }
        name:     { type: string, minLength: 1, maxLength: 100 }
        totp:                       # optional
          type: string
          maxLength: 64
          description: >-
            TOTP code or recovery code, required only when the account has
            two-factor authentication enabled.
```

**Android follow-up:** the app should, on a `401` from `POST /ut/v1/keys` for an account with 2FA
on, prompt for the authenticator code (or a recovery code) and resend the request with the `totp`
field. Until then, a user with 2FA enabled can still enroll a new device from the admin panel or
the web player (both support the second step), or temporarily from the app by appending the code if
the client allows it. Existing device keys keep working regardless.
