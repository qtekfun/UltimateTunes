# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Server-wide YouTube account cookies (D14): the encrypted store and the `/ut/v1` endpoints.

The admin (or the Android app, on the admin's behalf) uploads a Netscape `cookies.txt` exported
from a throwaway account; the api validates it, seals it with Fernet under
`UT_YTDLP_COOKIES_KEY` (`auth/secretbox.py`), and keeps only the ciphertext and a non-secret
status in the `settings` table. The api decrypts it and hands it to the worker **only** in a
download job's claim response (`jobs/internal_api.py`); the worker (no database) uses it for one
download and deletes its private copy. The cookies text is never logged and never audited.
"""
