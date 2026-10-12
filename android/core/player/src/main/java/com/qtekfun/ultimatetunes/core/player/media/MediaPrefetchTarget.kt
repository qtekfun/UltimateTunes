// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

@file:OptIn(UnstableApi::class)

package com.qtekfun.ultimatetunes.core.player.media

import androidx.annotation.OptIn
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DataSpec
import androidx.media3.datasource.cache.CacheWriter
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.model.RequestReason
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.player.cache.CachePolicy
import com.qtekfun.ultimatetunes.core.player.prefetch.PrefetchTarget
import java.io.IOException
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.job
import kotlinx.coroutines.withContext

/** The [PrefetchTarget] of the real player: the API and Media3's cache writer. */
class MediaPrefetchTarget(
    private val api: TunesApi,
    private val caches: MediaCaches,
    private val sources: MediaDataSources,
    private val io: CoroutineDispatcher = Dispatchers.IO
) : PrefetchTarget {
    override fun isAvailable(id: SongId): Boolean =
        caches.hasStart(CachePolicy.cacheKey(id), CachePolicy.PRELOAD_BYTES)

    override suspend fun requestOnServer(id: SongId): Boolean =
        api.requestTrack(id, RequestReason.PREFETCH) is TunesResult.Success

    override suspend fun preload(id: SongId, bytes: Long): Boolean {
        val url = api.streamUrl(id) ?: return false
        return withContext(io) {
            val spec = DataSpec.Builder()
                .setUri(url.toString())
                .setKey(CachePolicy.cacheKey(id))
                .setLength(bytes)
                .build()
            val writer = CacheWriter(sources.playCache.createDataSource(), spec, null, null)
            val stop = coroutineContext.job.invokeOnCompletion { writer.cancel() }
            try {
                writer.cache()
                true
            } catch (ignored: IOException) {
                // Includes the interruption of a cancelled preload; the planner retries later.
                false
            } finally {
                stop.dispose()
            }
        }
    }
}
