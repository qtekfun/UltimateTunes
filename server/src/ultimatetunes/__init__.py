# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""UltimateTunes server: OpenSubsonic API, library and on-demand YouTube Music fetching."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("ultimatetunes")
except PackageNotFoundError:  # pragma: no cover - only when running from an unbuilt tree
    __version__ = "0.0.0"
