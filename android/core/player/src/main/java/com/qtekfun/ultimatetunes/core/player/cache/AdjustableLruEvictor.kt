// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

@file:OptIn(UnstableApi::class)

package com.qtekfun.ultimatetunes.core.player.cache

import androidx.annotation.OptIn
import androidx.media3.common.C
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.cache.Cache
import androidx.media3.datasource.cache.CacheEvictor
import androidx.media3.datasource.cache.CacheSpan
import java.util.TreeSet

/**
 * Least-recently-used eviction like Media3's `LeastRecentlyUsedCacheEvictor`, but with a limit
 * that Settings can change while the cache is open ([resize]); `SimpleCache` takes its evictor
 * once, at construction.
 *
 * `SimpleCache` calls the listener methods while holding its own lock, so every access to this
 * evictor's state happens under the cache's lock: [resize] takes it too, in the same order.
 */
class AdjustableLruEvictor(maxBytes: Long) : CacheEvictor {
    private val spans = TreeSet(LEAST_RECENTLY_USED_FIRST)
    private var currentSize = 0L

    /** The current limit in bytes. */
    var maxBytes: Long = maxBytes
        private set

    /** Bytes the evictor counts as cached. */
    val cachedBytes: Long get() = currentSize

    /** Sets a new limit and evicts at once whatever no longer fits in [cache]. */
    fun resize(cache: Cache, newMaxBytes: Long) {
        synchronized(cache) {
            maxBytes = newMaxBytes
            evict(cache, 0)
        }
    }

    override fun requiresCacheSpanTouches(): Boolean = true

    override fun onCacheInitialized() = Unit

    override fun onStartFile(cache: Cache, key: String, position: Long, length: Long) {
        if (length != C.LENGTH_UNSET.toLong()) evict(cache, length)
    }

    override fun onSpanAdded(cache: Cache, span: CacheSpan) {
        spans.add(span)
        currentSize += span.length
        evict(cache, 0)
    }

    override fun onSpanRemoved(cache: Cache, span: CacheSpan) {
        spans.remove(span)
        currentSize -= span.length
    }

    override fun onSpanTouched(cache: Cache, oldSpan: CacheSpan, newSpan: CacheSpan) {
        onSpanRemoved(cache, oldSpan)
        onSpanAdded(cache, newSpan)
    }

    private fun evict(cache: Cache, requiredSpace: Long) {
        while (currentSize + requiredSpace > maxBytes && spans.isNotEmpty()) {
            // removeSpan calls onSpanRemoved, which updates spans and currentSize.
            cache.removeSpan(spans.first())
        }
    }
}

/** Oldest touch first; spans touched at the same time in their natural order (key, position). */
private val LEAST_RECENTLY_USED_FIRST: Comparator<CacheSpan> =
    compareBy<CacheSpan> { it.lastTouchTimestamp }.thenComparator { a, b -> a.compareTo(b) }
