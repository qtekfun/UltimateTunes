// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.library

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test

class SearchTextTest {
    @Test
    fun `lowercase, without accents, single spaces`() {
        assertEquals("cancion del nino", SearchText.of("  Canción   del NIÑO "))
        assertEquals("sigur ros bjork", SearchText.of("Sigur Rós", null, "Björk"))
        assertEquals("motorhead smorrebrod strasse", SearchText.of("Motörhead Smørrebrød Straße"))
        assertEquals("", SearchText.of(null, null))
    }
}
