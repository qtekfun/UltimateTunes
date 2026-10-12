# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Who a catalog lookup is charged to (`search.guard.GuardedCatalog`, per-user budget).

The routers set the caller right after authentication (`set_caller`): the OpenSubsonic
pipeline in `subsonic/router.py` and `core.authn.current_principal` on `/ut/v1`. The value
lives in a `ContextVar`, so it follows the request's task (and `run_in_threadpool`, which copies
the context) and never leaks into another request. Code that runs without a caller (anything
outside a request) is charged to one shared anonymous bucket, so nothing bypasses the budget
by accident. Background work with a budget of its own (imports, `import:catalog`) runs inside
`unmetered()`.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

# The bucket name of callers without a user.
ANONYMOUS = "-"


# The user bucket to charge; None: not charged to any user's catalog budget (`unmetered`).
_CALLER: ContextVar[str | None] = ContextVar("ut_catalog_caller", default=ANONYMOUS)


def set_caller(user_id: str | None) -> None:
    """The current request is made by `user_id` (None: anonymous, the shared bucket)."""
    _CALLER.set(user_id or ANONYMOUS)


def current_bucket() -> str | None:
    """The user bucket to charge, or None when the current work is unmetered."""
    return _CALLER.get()


@contextmanager
def unmetered() -> Iterator[None]:
    """Catalog lookups inside are not charged to a user (work with its own budget)."""
    token = _CALLER.set(None)
    try:
        yield
    finally:
        _CALLER.reset(token)
