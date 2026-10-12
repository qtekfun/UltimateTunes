// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

@file:OptIn(UnstableApi::class)

package com.qtekfun.ultimatetunes.core.player.export

import android.net.Uri
import androidx.annotation.OptIn
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DataSourceInputStream
import androidx.media3.datasource.DataSpec
import androidx.media3.datasource.cache.Cache
import androidx.media3.datasource.cache.CacheDataSource
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.player.cache.CachePolicy
import com.qtekfun.ultimatetunes.core.player.media.MediaCacheView
import com.qtekfun.ultimatetunes.core.player.media.MediaCaches
import java.io.InputStream

/**
 * Songs fully on the phone (RF-14): an offline download first, else a library song complete in
 * the play cache. Read from the cache only: a missing byte fails the read instead of reaching the
 * network. Both caches hold the server's original file (`download` and `stream` never transcode).
 */
class CacheExportSource(private val caches: MediaCaches) : ExportSource {
    override fun open(id: SongId): InputStream? {
        if (id.isExternal) return null
        val key = CachePolicy.cacheKey(id)
        val cache = listOf(caches.downloads, caches.play).firstOrNull { isComplete(it, key) }
            ?: return null
        // No upstream: anything not cached fails with an IOException.
        val source = CacheDataSource(cache, null)
        val spec = DataSpec.Builder().setUri(Uri.parse("$SCHEME:${Uri.encode(key)}"))
            .setKey(key)
            .build()
        return DataSourceInputStream(source, spec)
    }

    private fun isComplete(cache: Cache, key: String): Boolean {
        val view = MediaCacheView(cache)
        return CachePolicy.isComplete(
            view.contentLength(key),
            view.cachedBytes(key, Long.MAX_VALUE)
        )
    }

    private companion object {
        /** Never fetched: the key is all the cache needs. */
        const val SCHEME = "ut-export"
    }
}
