// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.cache

import androidx.media3.common.C
import androidx.media3.datasource.cache.Cache
import androidx.media3.datasource.cache.CacheSpan
import io.mockk.every
import io.mockk.mockk
import io.mockk.verify
import java.io.File
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class AdjustableLruEvictorTest {
    private val evictor = AdjustableLruEvictor(maxBytes = 100)
    private val removed = mutableListOf<CacheSpan>()

    /** A cache whose removeSpan calls back into the evictor, like SimpleCache does. */
    private val cache: Cache = mockk {
        every { removeSpan(any()) } answers {
            val span = firstArg<CacheSpan>()
            removed += span
            evictor.onSpanRemoved(this@mockk, span)
        }
    }

    private fun span(key: String, length: Long, touched: Long, position: Long = 0) =
        CacheSpan(key, position, length, touched, File("/cache/$key.$position.$touched"))

    @Test
    fun `the evictor needs touches and does nothing on init`() {
        assertTrue(evictor.requiresCacheSpanTouches())
        evictor.onCacheInitialized()
        assertEquals(0, evictor.cachedBytes)
        assertEquals(100, evictor.maxBytes)
    }

    @Test
    fun `adding beyond the limit evicts the least recently used spans first`() {
        val oldest = span("a", 40, touched = 1)
        val middle = span("b", 40, touched = 2)
        val newest = span("c", 40, touched = 3)
        evictor.onSpanAdded(cache, middle)
        evictor.onSpanAdded(cache, oldest)
        assertEquals(80, evictor.cachedBytes)

        evictor.onSpanAdded(cache, newest)

        assertEquals(listOf(oldest), removed)
        assertEquals(80, evictor.cachedBytes)
    }

    @Test
    fun `spans touched at the same time are ordered by key and position`() {
        val second = span("k", 60, touched = 5, position = 60)
        val first = span("k", 60, touched = 5, position = 0)
        evictor.onSpanAdded(cache, second)
        evictor.onSpanAdded(cache, first)

        assertEquals(listOf(first), removed)
    }

    @Test
    fun `a touched span becomes the most recently used`() {
        val a = span("a", 40, touched = 1)
        val b = span("b", 40, touched = 2)
        evictor.onSpanAdded(cache, a)
        evictor.onSpanAdded(cache, b)
        val aTouched = span("a", 40, touched = 3)
        evictor.onSpanTouched(cache, a, aTouched)

        evictor.onSpanAdded(cache, span("c", 40, touched = 4))

        assertEquals(listOf(b), removed)
    }

    @Test
    fun `starting a file of known length makes room first`() {
        val a = span("a", 60, touched = 1)
        evictor.onSpanAdded(cache, a)

        evictor.onStartFile(cache, "b", 0, 50)

        assertEquals(listOf(a), removed)
        assertEquals(0, evictor.cachedBytes)
    }

    @Test
    fun `starting a file of unknown length evicts nothing`() {
        evictor.onSpanAdded(cache, span("a", 60, touched = 1))

        evictor.onStartFile(cache, "b", 0, C.LENGTH_UNSET.toLong())

        assertTrue(removed.isEmpty())
    }

    @Test
    fun `resizing down evicts at once and resizing up keeps everything`() {
        val a = span("a", 30, touched = 1)
        val b = span("b", 30, touched = 2)
        val c = span("c", 30, touched = 3)
        listOf(a, b, c).forEach { evictor.onSpanAdded(cache, it) }

        evictor.resize(cache, 500)
        assertTrue(removed.isEmpty())
        assertEquals(500, evictor.maxBytes)

        evictor.resize(cache, 40)
        assertEquals(listOf(a, b), removed)
        assertEquals(30, evictor.cachedBytes)
        assertEquals(40, evictor.maxBytes)
    }

    @Test
    fun `a limit of zero empties the cache and stops when nothing is left`() {
        evictor.onSpanAdded(cache, span("a", 30, touched = 1))
        evictor.resize(cache, 0)
        assertEquals(0, evictor.cachedBytes)

        // Nothing left to evict: a file that cannot fit does not loop forever.
        evictor.onStartFile(cache, "b", 0, 10)
        verify(exactly = 1) { cache.removeSpan(any()) }
    }
}
