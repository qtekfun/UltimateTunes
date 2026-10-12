// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.cache

import com.qtekfun.ultimatetunes.core.api.model.SongId
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class CachePolicyTest {
    private val library = SongId("0190a5c8-7b1e-7c4a-9d1e-2f3a4b5c6d7e")
    private val external = SongId("yt:dQw4w9WgXcQ")

    @Test
    fun `the cache key is the played id, library or yt`() {
        assertEquals(library.value, CachePolicy.cacheKey(library))
        assertEquals("yt:dQw4w9WgXcQ", CachePolicy.cacheKey(external))
        assertEquals(external, CachePolicy.songOf(CachePolicy.cacheKey(external)))
    }

    @Test
    fun `the size limit follows the setting with a floor`() {
        assertEquals(2048L * 1024 * 1024, CachePolicy.maxBytes(CachePolicy.DEFAULT_CACHE_MB))
        assertEquals(10_240L * 1024 * 1024, CachePolicy.maxBytes(10_240))
        assertEquals(256L * 1024 * 1024, CachePolicy.maxBytes(0))
        assertEquals(256L * 1024 * 1024, CachePolicy.maxBytes(-5))
    }

    @Test
    fun `the read timeout is within the 20 to 30 seconds of T03a`() {
        assertTrue(CachePolicy.READ_TIMEOUT_SECONDS in 20L..30L)
    }

    @Test
    fun `content is complete only with a known length fully cached`() {
        assertTrue(CachePolicy.isComplete(100, 100))
        assertTrue(CachePolicy.isComplete(0, 0))
        assertFalse(CachePolicy.isComplete(100, 99))
        assertFalse(CachePolicy.isComplete(null, 5_000))
        assertFalse(CachePolicy.isComplete(-1, 5_000))
    }

    @Test
    fun `library entries are always kept, even incomplete`() {
        val entry = CacheEntry(library.value, contentLength = null, cachedBytes = 10)
        assertEquals(Disposition.Keep, CachePolicy.disposition(entry, emptySet(), setOf(library)))
    }

    @Test
    fun `entries in use are kept, even archived or incomplete`() {
        val entry = CacheEntry(external.value, contentLength = 100, cachedBytes = 10)
        assertEquals(
            Disposition.Keep,
            CachePolicy.disposition(entry, setOf(external.value), setOf(external))
        )
    }

    @Test
    fun `an archived yt entry is dropped even when complete`() {
        val entry = CacheEntry(external.value, contentLength = 100, cachedBytes = 100)
        assertEquals(
            Disposition.Drop(DropReason.ARCHIVED),
            CachePolicy.disposition(entry, emptySet(), setOf(external))
        )
    }

    @Test
    fun `an incomplete first play is dropped, with or without a known size`() {
        val partial = CacheEntry(external.value, contentLength = 100, cachedBytes = 40)
        val unsized = CacheEntry(external.value, contentLength = null, cachedBytes = 40)
        val expected = Disposition.Drop(DropReason.INCOMPLETE_FIRST_PLAY)
        assertEquals(expected, CachePolicy.disposition(partial, emptySet(), emptySet()))
        assertEquals(expected, CachePolicy.disposition(unsized, emptySet(), emptySet()))
    }

    @Test
    fun `a complete first play that is not archived yet stays`() {
        val entry = CacheEntry(external.value, contentLength = 100, cachedBytes = 100)
        assertEquals(Disposition.Keep, CachePolicy.disposition(entry, emptySet(), emptySet()))
    }
}

class CacheJanitorTest {
    private class FakeCache(val entries: MutableMap<String, Pair<Long?, Long>>) : CacheView {
        val limits = mutableListOf<Long>()

        override fun keys(): Set<String> = entries.keys.toSet()

        override fun contentLength(key: String): Long? = entries.getValue(key).first

        override fun cachedBytes(key: String, limit: Long): Long {
            limits += limit
            return minOf(entries.getValue(key).second, limit)
        }

        override fun remove(key: String) {
            entries.remove(key)
        }
    }

    @Test
    fun `sweep drops archived and incomplete yt entries and keeps the rest`() {
        val cache = FakeCache(
            mutableMapOf(
                "0190a5c8-0000-7000-8000-000000000001" to (null to 10L),
                "yt:AAAAAAAAAAA" to (100L to 100L),
                "yt:BBBBBBBBBBB" to (100L to 50L),
                "yt:CCCCCCCCCCC" to (null to 50L),
                "yt:DDDDDDDDDDD" to (100L to 100L),
                "yt:EEEEEEEEEEE" to (100L to 10L)
            )
        )
        val dropped = CacheJanitor(cache).sweep(
            inUse = setOf("yt:EEEEEEEEEEE"),
            archived = setOf(SongId("yt:DDDDDDDDDDD"))
        )

        assertEquals(
            mapOf(
                "yt:BBBBBBBBBBB" to DropReason.INCOMPLETE_FIRST_PLAY,
                "yt:CCCCCCCCCCC" to DropReason.INCOMPLETE_FIRST_PLAY,
                "yt:DDDDDDDDDDD" to DropReason.ARCHIVED
            ),
            dropped
        )
        assertEquals(
            setOf("0190a5c8-0000-7000-8000-000000000001", "yt:AAAAAAAAAAA", "yt:EEEEEEEEEEE"),
            cache.keys()
        )
        // A known length bounds the byte count; an unknown one asks for everything cached.
        assertTrue(Long.MAX_VALUE in cache.limits)
        assertTrue(100L in cache.limits)
    }
}
