// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.player

import com.qtekfun.ultimatetunes.ui.lyrics.LyricLineUi
import com.qtekfun.ultimatetunes.ui.lyrics.LyricsContent
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNotEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class PlayerCardsTest {
    private val synced = LyricsContent(
        lines = listOf(
            LyricLineUi("First", 1_000),
            LyricLineUi("", 2_000),
            LyricLineUi("Second", 3_000),
            LyricLineUi("Third", 5_000)
        ),
        synced = true
    )

    @Test
    fun `the card follows the line being sung and the one after it`() {
        // Before the first line: the first one, and what comes next.
        assertEquals("First" to "Second", lyricsPreview(synced, 0))
        // Blank lines (instrumental breaks) are skipped.
        assertEquals("First" to "Second", lyricsPreview(synced, 2_500))
        assertEquals("Second" to "Third", lyricsPreview(synced, 3_000))
        assertEquals("Third" to null, lyricsPreview(synced, 60_000))
    }

    @Test
    fun `plain lyrics show their first lines, and no lyrics show nothing`() {
        val plain = LyricsContent(
            lines = listOf(LyricLineUi("One", null), LyricLineUi("Two", null)),
            synced = false
        )
        assertEquals("One" to "Two", lyricsPreview(plain, 90_000))
        assertNull(lyricsPreview(null, 0))
        assertNull(lyricsPreview(LyricsContent(listOf(LyricLineUi(" ", null)), false), 0))
    }

    @Test
    fun `the scrubber's bars are the same for a song and never vanish`() {
        val bars = barHeights("song-1", 60)
        assertEquals(60, bars.size)
        assertEquals(bars, barHeights("song-1", 60))
        assertNotEquals(bars, barHeights("song-2", 60))
        assertTrue(bars.all { it in 0.28f..1f })
        assertEquals(emptyList<Float>(), barHeights("song-1", 0))
    }
}
