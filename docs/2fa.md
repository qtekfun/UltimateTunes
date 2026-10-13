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

A covered user who has not enrolled yet is signed in but sent straight to the setup page, and
cannot turn the factor off while the policy covers them. The policy is an environment variable so
it is part of the deployment, not something a single admin session can switch.

## Brute force and replay

- The password lockout/back-off (per IP and per username, SECURITY.md) runs **in front** of the
  second step unchanged.
- The second step has its **own** lockout bucket (`auth:2fa:<user id>`): repeated wrong codes lock
  that user's second step for `UT_AUTH_LOCKOUT_S` after `UT_AUTH_MAX_FAILURES_PER_USER` tries.
- A code is accepted within `UT_AUTH_2FA_WINDOW` (default ±1) 30 s steps for clock drift, and the
  **last accepted step is remembered**, so a code cannot be replayed inside its validity window
  (RFC 6238 §5.2).
- The shared secret and the recovery codes never appear in logs, the audit log or an error. Every
  outcome is an `auth.2fa` security event with the user id and a reason, never a code.

## Secret at rest — caveat and proposal

The TOTP shared secret **must be reversible** (the server recomputes codes from it), so it is
stored in the database (`user_totp.secret`). The current dependency set has **no AEAD library**
(same note as the authenticated-notification credentials in `SECURITY.md`), so the secret is stored
as-is.

**Protect `/data`.** A stolen database exposes the TOTP secrets (an attacker who also has the
password could then generate codes). The recovery codes are **not** at risk: they are stored only
as Argon2id hashes.

A follow-up proposal, left for the owner to approve, is to add a vetted AEAD dependency and encrypt
`user_totp.secret` at rest with a key from an environment variable / Docker secret (so the database
alone is not enough). The recommended package is **`cryptography`** (Apache-2.0 **OR** BSD-3-Clause;
GPL-3.0-compatible), using **`cryptography.fernet.Fernet`** (AES-128-CBC + HMAC-SHA256). An
alternative is **`PyNaCl`** (Apache-2.0; libsodium secretbox, XSalsa20-Poly1305). Either is a new
dependency and therefore needs the owner's explicit approval and a license check before it is added
(CLAUDE.md). This is **not** implemented in this change.

## `POST /ut/v1/keys` and the app — additive contract change (proposed)

The server reads an **optional** `totp` field on `POST /ut/v1/keys` and, when the account has 2FA
enabled, requires a valid code (a TOTP code or a recovery code) in addition to the password, so a
stolen password alone cannot enroll a new device. The field is optional and is consulted only for
2FA-enabled accounts, so the frozen `contracts/openapi/ut-v1.yaml` and clients that do not send it
are unaffected — `ut-v1.yaml` was **not** edited (it is frozen per wave).

Proposed additive change for the coordinator to apply to `ut-v1.yaml` (`CreateKeyRequest`):

```yaml
    CreateKeyRequest:
      properties:
        username: { type: string, minLength: 1, maxLength: 64 }
        password: { type: string, minLength: 1, maxLength: 1024 }
        name:     { type: string, minLength: 1, maxLength: 100 }
        totp:                       # NEW, optional
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
