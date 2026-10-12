// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.model

import com.qtekfun.ultimatetunes.core.api.ErrorKind
import com.qtekfun.ultimatetunes.core.api.TunesError
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.ui.player.DefaultPlayerColors
import com.qtekfun.ultimatetunes.ui.player.playerColorsFrom
import java.io.IOException
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNotEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class UiModelsTest {
    @Test
    fun `failures map to what the user can do about them`() {
        val error = TunesError(ErrorKind.INTERNAL)
        assertEquals(LoadError.NETWORK, TunesResult.NetworkError(IOException()).toLoadError())
        assertEquals(LoadError.UNAUTHORIZED, TunesResult.Unauthorized(error, 401).toLoadError())
        assertEquals(LoadError.NOT_CONFIGURED, TunesResult.NotConfigured.toLoadError())
        assertEquals(LoadError.SERVER, TunesResult.ApiError(error, 500).toLoadError())
        assertEquals(LoadError.SERVER, TunesResult.ProtocolError("x", 200).toLoadError())
    }

    @Test
    fun `durations read as minutes and seconds`() {
        assertEquals("0:00", formatDuration(0))
        assertEquals("0:00", formatDuration(-3))
        assertEquals("3:34", formatDuration(214))
        assertEquals("59:59", formatDuration(3599))
        assertEquals("1:00:05", formatDuration(3605))
    }

    @Test
    fun `player colours come from the artwork, darkened, or fall back`() {
        assertEquals(DefaultPlayerColors, playerColorsFrom(null, null))
        val red = playerColorsFrom(0xFFFF0000.toInt(), null)
        assertNotEquals(DefaultPlayerColors, red)
        // Still red, but darker so white text reads on it.
        assertTrue(red.top.red > red.top.green && red.top.red < 1f)
        assertTrue(red.bottom.red < red.top.red)
        // The bottom of the gradient follows the dark muted colour when there is one.
        val withMuted = playerColorsFrom(0xFFFF0000.toInt(), 0xFF0000FF.toInt())
        assertTrue(withMuted.bottom.blue > withMuted.bottom.red)
    }
}
