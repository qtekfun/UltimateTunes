// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.model

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test

class CoverSizeTest {
    @Test
    fun `a cover URL asks for another size`() {
        assertEquals(
            "https://music.test/rest/getCoverArt?id=al-1&size=1200",
            "https://music.test/rest/getCoverArt?id=al-1&size=600".withCoverSize(PLAYER_ARTWORK_PX)
        )
    }

    @Test
    fun `a URL without a size is left as it is`() {
        val url = "https://images.test/cover.jpg?resize=600"
        assertEquals(url, url.withCoverSize(PLAYER_ARTWORK_PX))
    }
}
