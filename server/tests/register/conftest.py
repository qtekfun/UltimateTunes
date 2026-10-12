# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The in-process api fixture of `test_register.py`, shared with the end-to-end tests."""

from tests.register.test_register import anyio_backend, api

__all__ = ["anyio_backend", "api"]
