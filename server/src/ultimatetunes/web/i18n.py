# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""English and Spanish for the web player.

As in the admin panel (`admin/i18n.py`, whose `Accept-Language` negotiation is reused):
templates call `_("English text")` or `_("... %(name)s ...", name=value)`; English is the
message id and the default; the Spanish catalog is `catalog_es.py`, and a test checks that
every message of the templates and of the code has a Spanish entry. `player.js` gets its few
texts from `data-t-*` attributes of the player bar, translated here.
"""

from collections.abc import Mapping

from ultimatetunes.admin.i18n import Lang, Translate
from ultimatetunes.web.catalog_es import ES

CATALOGS: Mapping[Lang, Mapping[str, str]] = {"en": {}, "es": ES}


def translator(lang: Lang) -> Translate:
    catalog = CATALOGS[lang]

    def gettext(message: str, /, **values: object) -> str:
        text = catalog.get(message, message)
        return text % values if values else text

    return gettext
