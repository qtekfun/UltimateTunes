// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

@file:OptIn(UnstableApi::class)

package com.qtekfun.ultimatetunes.core.player.offline

import android.content.Context
import androidx.annotation.OptIn
import androidx.core.net.toUri
import androidx.media3.common.util.UnstableApi
import androidx.media3.database.DatabaseProvider
import androidx.media3.exoplayer.offline.Download
import androidx.media3.exoplayer.offline.DownloadIndex
import androidx.media3.exoplayer.offline.DownloadManager
import androidx.media3.exoplayer.offline.DownloadRequest
import androidx.media3.exoplayer.offline.DownloadService
import androidx.media3.exoplayer.scheduler.Requirements
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.player.PlayableTrack
import com.qtekfun.ultimatetunes.core.player.PlayerSettingsSource
import com.qtekfun.ultimatetunes.core.player.cache.CachePolicy
import com.qtekfun.ultimatetunes.core.player.media.MediaCaches
import com.qtekfun.ultimatetunes.core.player.media.MediaDataSources
import dagger.hilt.android.qualifiers.ApplicationContext
import java.util.concurrent.Executors
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.Json

/** One offline download as the Downloads screen shows it. */
data class OfflineItem(val track: PlayableTrack, val state: OfflineState, val percent: Float)

enum class OfflineState { QUEUED, DOWNLOADING, DONE, FAILED }

/**
 * The offline downloads (RF-12) with Media3's [DownloadManager], in their own cache that nothing
 * evicts. The original file comes from `download` (no transcoding), stored under the song id, so
 * the player finds it with the same key as a cached play. Downloads wait for Wi-Fi when the
 * setting says so.
 */
@Singleton
class OfflineDownloads @Inject constructor(
    @param:ApplicationContext private val context: Context,
    private val api: TunesApi,
    private val caches: MediaCaches,
    private val sources: MediaDataSources,
    private val database: DatabaseProvider,
    settings: PlayerSettingsSource
) : DownloadQueue {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val state = MutableStateFlow<List<OfflineItem>>(emptyList())
    private val idle = MutableStateFlow(true)

    /** Every download with its progress, newest first. */
    val items: StateFlow<List<OfflineItem>> = state.asStateFlow()

    /** The Media3 manager, created on the main thread on first use. */
    val manager: DownloadManager by lazy {
        DownloadManager(
            context,
            database,
            caches.downloads,
            sources.http,
            Executors.newFixedThreadPool(PARALLEL_DOWNLOADS)
        ).apply {
            maxParallelDownloads = PARALLEL_DOWNLOADS
            addListener(object : DownloadManager.Listener {
                override fun onInitialized(downloadManager: DownloadManager) = refresh()

                override fun onIdle(downloadManager: DownloadManager) {
                    idle.value = true
                }

                override fun onDownloadChanged(
                    downloadManager: DownloadManager,
                    download: Download,
                    finalException: Exception?
                ) = refresh()

                override fun onDownloadRemoved(
                    downloadManager: DownloadManager,
                    download: Download
                ) = refresh()
            })
            // DownloadService resumes on creation; downloads must run without it too (sync job).
            resumeDownloads()
        }
    }

    init {
        scope.launch {
            settings.settings.map { it.downloadOnWifiOnly }.distinctUntilChanged().collect {
                manager.requirements = requirements(it)
            }
        }
    }

    override suspend fun knownIds(): Set<SongId> {
        val index = onMain { manager }.downloadIndex
        return withContext(Dispatchers.IO) { readIndex(index) }
            .filter { it.state != Download.STATE_FAILED }
            .mapTo(HashSet()) { SongId(it.request.id) }
    }

    override suspend fun add(track: PlayableTrack) {
        val url = api.downloadUrl(track.id) ?: return
        val request = DownloadRequest.Builder(track.id.value, url.toString().toUri())
            .setCustomCacheKey(CachePolicy.cacheKey(track.id))
            .setData(JSON.encodeToString(track).encodeToByteArray())
            .build()
        onMain {
            manager.addDownload(request)
            showProgress()
        }
    }

    override suspend fun remove(id: SongId) = onMain { manager.removeDownload(id.value) }

    /**
     * Waits until no download is running, at most [timeoutMs]; true if that happened. Downloads
     * waiting for Wi-Fi do not count as running.
     */
    suspend fun awaitIdle(timeoutMs: Long): Boolean {
        idle.value = onMain { manager.isIdle }
        return withTimeoutOrNull(timeoutMs) { idle.first { it } } != null
    }

    /** Starts the download service for the progress notification; not allowed in background. */
    private fun showProgress() {
        try {
            DownloadService.start(context, OfflineDownloadService::class.java)
        } catch (ignored: IllegalStateException) {
            // Background start refused (Android 12+): downloads go on while the process lives.
        }
    }

    private fun refresh() {
        idle.value = manager.isIdle
        val index = manager.downloadIndex
        scope.launch {
            state.value = withContext(Dispatchers.IO) { readIndex(index) }.mapNotNull(::itemOf)
        }
    }

    private fun readIndex(index: DownloadIndex): List<Download> = buildList {
        index.getDownloads().use { cursor ->
            while (cursor.moveToNext()) add(cursor.download)
        }
    }.sortedByDescending { it.startTimeMs }

    private fun itemOf(download: Download): OfflineItem? {
        val track = try {
            JSON.decodeFromString<PlayableTrack>(download.request.data.decodeToString())
        } catch (ignored: IllegalArgumentException) {
            return null
        }
        val state = when (download.state) {
            Download.STATE_COMPLETED -> OfflineState.DONE
            Download.STATE_DOWNLOADING -> OfflineState.DOWNLOADING
            Download.STATE_FAILED -> OfflineState.FAILED
            else -> OfflineState.QUEUED
        }
        return OfflineItem(track, state, download.percentDownloaded.coerceAtLeast(0f))
    }

    private suspend fun <T> onMain(block: () -> T): T = withContext(Dispatchers.Main.immediate) {
        block()
    }

    private companion object {
        const val PARALLEL_DOWNLOADS = 2
        val JSON = Json { ignoreUnknownKeys = true }

        fun requirements(wifiOnly: Boolean) =
            Requirements(if (wifiOnly) Requirements.NETWORK_UNMETERED else Requirements.NETWORK)
    }
}
