// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

@file:OptIn(UnstableApi::class)

package com.qtekfun.ultimatetunes.core.player.media

import androidx.annotation.OptIn
import androidx.media3.common.C
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DataSource
import androidx.media3.datasource.cache.Cache
import androidx.media3.datasource.cache.CacheDataSource
import androidx.media3.datasource.cache.ContentMetadata
import androidx.media3.datasource.okhttp.OkHttpDataSource
import com.qtekfun.ultimatetunes.core.player.cache.AdjustableLruEvictor
import com.qtekfun.ultimatetunes.core.player.cache.CachePolicy
import com.qtekfun.ultimatetunes.core.player.cache.CacheView
import java.util.concurrent.TimeUnit
import okhttp3.OkHttpClient

/**
 * The two Media3 caches (RF-12): [play], the LRU cache every play goes through, and [downloads],
 * the offline downloads, which nothing evicts. Both use the played id as key.
 */
class MediaCaches(val play: Cache, val evictor: AdjustableLruEvictor, val downloads: Cache) {
    /** Applies a new size limit to the play cache at once. */
    fun resizePlayCache(cacheSizeMb: Int) {
        evictor.resize(play, CachePolicy.maxBytes(cacheSizeMb))
    }

    /** True when the first [bytes] of [key] (or all of it, if shorter) are on the phone. */
    fun hasStart(key: String, bytes: Long): Boolean =
        startCached(play, key, bytes) || startCached(downloads, key, bytes)

    private fun startCached(cache: Cache, key: String, bytes: Long): Boolean {
        val length = ContentMetadata.getContentLength(cache.getContentMetadata(key))
        val needed = if (length >= 0) minOf(length, bytes) else bytes
        return needed > 0 && cache.isCached(key, 0, needed)
    }
}

/** A Media3 [Cache] as the janitor's [CacheView]. */
class MediaCacheView(private val cache: Cache) : CacheView {
    override fun keys(): Set<String> = cache.keys

    override fun contentLength(key: String): Long? =
        ContentMetadata.getContentLength(cache.getContentMetadata(key)).takeIf { it >= 0 }

    override fun cachedBytes(key: String, limit: Long): Long = cache.getCachedBytes(
        key,
        0,
        if (limit ==
            Long.MAX_VALUE
        ) {
            C.LENGTH_UNSET.toLong()
        } else {
            limit
        }
    )

    override fun remove(key: String) = cache.removeResource(key)
}

/**
 * Media3 data sources over the app's authenticated OkHttp client (`@TunesHttpClient`, which adds
 * the key at send time; SPEC §11 T02), with the longer read timeout a first play needs (T03a).
 */
class MediaDataSources(client: OkHttpClient, caches: MediaCaches) {
    /** Plain HTTP to the server. */
    val http: DataSource.Factory = OkHttpDataSource.Factory(
        client.newBuilder()
            .readTimeout(CachePolicy.READ_TIMEOUT_SECONDS, TimeUnit.SECONDS)
            .build()
    )

    /** Reads through the play cache, writing what it fetches. */
    val playCache: CacheDataSource.Factory = CacheDataSource.Factory()
        .setCache(caches.play)
        .setUpstreamDataSourceFactory(http)
        .setFlags(CacheDataSource.FLAG_IGNORE_CACHE_ON_ERROR)

    /** What the player uses: offline downloads first (read-only), then the play cache. */
    val playback: DataSource.Factory = CacheDataSource.Factory()
        .setCache(caches.downloads)
        .setCacheWriteDataSinkFactory(null)
        .setUpstreamDataSourceFactory(playCache)
}
