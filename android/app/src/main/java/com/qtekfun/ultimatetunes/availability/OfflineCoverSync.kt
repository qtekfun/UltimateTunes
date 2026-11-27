// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.availability

import com.qtekfun.ultimatetunes.core.api.ServerConfigSource
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.di.TunesHttpClient
import com.qtekfun.ultimatetunes.core.api.model.CoverArtId
import com.qtekfun.ultimatetunes.core.player.PlayableTrack
import com.qtekfun.ultimatetunes.core.player.offline.OfflineState
import com.qtekfun.ultimatetunes.playback.OfflineControls
import java.io.IOException
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request

/** Keeps [OfflineCovers] in step with the finished downloads while the server can be asked. */
@Suppress("LongParameterList") // Collaborators are injected one by one.
@Singleton
class OfflineCoverSync internal constructor(
    private val covers: OfflineCovers,
    private val offline: OfflineControls,
    private val api: TunesApi,
    private val client: OkHttpClient,
    private val configSource: ServerConfigSource,
    private val connectivity: Connectivity,
    private val scope: CoroutineScope,
    private val io: CoroutineDispatcher
) {
    @Inject
    constructor(
        covers: OfflineCovers,
        offline: OfflineControls,
        api: TunesApi,
        @TunesHttpClient client: OkHttpClient,
        configSource: ServerConfigSource,
        connectivity: Connectivity
    ) : this(
        covers,
        offline,
        api,
        client,
        configSource,
        connectivity,
        CoroutineScope(SupervisorJob() + Dispatchers.Default),
        Dispatchers.IO
    )

    fun start() {
        scope.launch {
            combine(
                offline.items,
                offline.selection,
                configSource.config,
                connectivity.online
            ) { items, selection, config, online ->
                val done = items.filter { it.state == OfflineState.DONE }
                    .mapNotNullTo(HashSet()) { item ->
                        item.track.artworkUrl?.let(OfflineCovers::coverIdOf)
                    }
                // No downloads listed yet while something is kept: the list is still being read,
                // and nothing may be deleted on its account.
                val listed = items.isNotEmpty() || selection.isEmpty
                done.takeIf { listed && online && config != null }
            }
                .distinctUntilChanged()
                .collectLatest { ids ->
                    if (ids != null) withContext(io) { covers.keep(ids, ::fetch) }
                }
        }
    }

    private fun fetch(id: String): ByteArray? {
        val url = api.coverArtUrl(CoverArtId(id), PlayableTrack.ARTWORK_PX) ?: return null
        return try {
            client.newCall(Request.Builder().url(url).build()).execute().use { response ->
                val image = response.body.contentType()?.type == "image"
                if (response.isSuccessful && image) response.body.bytes() else null
            }
        } catch (ignored: IOException) {
            null
        }
    }
}
