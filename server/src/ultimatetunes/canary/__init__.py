# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The server canary (SPEC section 11): scheduled checks of the catalog (api side: one search,
one radio, one album page, one playlist read) whose results go to `canary_runs`, the admin
panel and notifications. Owner: PLAN T19. The download check runs in the worker (T08)."""
