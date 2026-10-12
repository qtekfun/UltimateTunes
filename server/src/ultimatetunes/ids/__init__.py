# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Identifiers (contracts/ids.md). Owned by PLAN T06, 100 % coverage.

T02 ships the UUIDv7 generator (`uuid7.new_id`) because every stream creates rows. T06 adds
virtual id parsing (`yt:`, `ytalbum:`, `ytartist:`) and resolution to library ids here.
"""

from ultimatetunes.ids.uuid7 import new_id

__all__ = ["new_id"]
