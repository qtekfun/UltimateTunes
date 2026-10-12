# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""English and Spanish for the admin panel and the `/` page.

Templates call `_("English text")`, or `_("... %(name)s ...", name=value)`; English is the
message id and the default. The Spanish catalog is `catalog_es.py`; a test checks that every
message used in a template or in the code has a Spanish entry. The language comes from the
`Accept-Language` header (English unless Spanish is preferred).
"""

from collections.abc import Callable, Mapping
from typing import Literal

from ultimatetunes.admin.catalog_es import ES

Lang = Literal["en", "es"]
CATALOGS: Mapping[Lang, Mapping[str, str]] = {"en": {}, "es": ES}
Translate = Callable[..., str]


def negotiate(accept_language: str | None) -> Lang:
    """The preferred of English and Spanish per `Accept-Language` (RFC 9110 q-values)."""
    best: tuple[float, Lang] = (0.0, "en")
    for position, item in enumerate((accept_language or "").split(",")):
        tag, _, params = item.strip().partition(";")
        primary = tag.strip().lower().split("-", 1)[0]
        if primary not in ("en", "es"):
            continue
        quality = 1.0
        name, _, value = params.strip().partition("=")
        if name.strip() == "q":
            try:
                quality = float(value)
            except ValueError:
                quality = 0.0
        # Earlier entries win ties; q=0 means "not acceptable".
        score = quality - position * 1e-6
        if quality > 0 and score > best[0]:
            best = (score, "es" if primary == "es" else "en")
    return best[1]


def translator(lang: Lang) -> Translate:
    catalog = CATALOGS[lang]

    def gettext(message: str, /, **values: object) -> str:
        text = catalog.get(message, message)
        return text % values if values else text

    return gettext
