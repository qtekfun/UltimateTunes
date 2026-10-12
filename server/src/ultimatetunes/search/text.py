# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Text normalisation for matching names (`*_norm` columns, search queries, cache keys).

`normalize` folds case and accents, turns punctuation into spaces and collapses whitespace:
`"  Héroes del Silencio — Entre dos Tierras!"` → `"heroes del silencio entre dos tierras"`.
Whoever writes a `*_norm` column (library scan, archive registration, materialization) should
use it, so a query matches whatever the library holds.
"""

import re
import unicodedata

_PUNCTUATION = re.compile(r"[^\w\s]+")
_SPACES = re.compile(r"\s+")
# A query is cut to this many tokens: enough for "artist title", bounded SQL.
MAX_TOKENS = 8


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _SPACES.sub(" ", _PUNCTUATION.sub(" ", stripped.casefold())).strip()


def tokens(text: str) -> list[str]:
    """Distinct normalised words of `text`, in order, at most `MAX_TOKENS`."""
    seen: list[str] = []
    for word in normalize(text).split(" "):
        if word and word not in seen:
            seen.append(word)
    return seen[:MAX_TOKENS]


def like_pattern(token: str) -> str:
    """`%token%` for `LIKE ? ESCAPE '\\'`, with the LIKE wildcards of the token escaped."""
    escaped = token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
