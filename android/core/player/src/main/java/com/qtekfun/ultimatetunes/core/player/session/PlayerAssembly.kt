// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

@file:OptIn(UnstableApi::class)

package com.qtekfun.ultimatetunes.core.player.session

import android.content.Context
import android.os.Process
import androidx.annotation.OptIn
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.common.util.BitmapLoader
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DataSourceBitmapLoader
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.session.MediaSession
import com.google.common.util.concurrent.Futures
import com.google.common.util.concurrent.ListenableFuture
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.player.PlayerSettingsSource
import com.qtekfun.ultimatetunes.core.player.cache.CacheJanitor
import com.qtekfun.ultimatetunes.core.player.cache.CachePolicy
import com.qtekfun.ultimatetunes.core.player.cache.StatusPoller
import com.qtekfun.ultimatetunes.core.player.gain.ReplayGainSource
import com.qtekfun.ultimatetunes.core.player.media.MediaCacheView
import com.qtekfun.ultimatetunes.core.player.media.MediaCaches
import com.qtekfun.ultimatetunes.core.player.media.MediaDataSources
import com.qtekfun.ultimatetunes.core.player.media.MediaItems
import com.qtekfun.ultimatetunes.core.player.media.MediaPrefetchTarget
import com.qtekfun.ultimatetunes.core.player.prefetch.PrefetchPlanner
import com.qtekfun.ultimatetunes.core.player.prefetch.Prefetcher
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers

/**
 * Builds the player of the session service: ExoPlayer over the cached data sources, with audio
 * focus, the "becoming noisy" pause and a network wake lock, and its [PlaybackEngine].
 */
@Singleton
class PlayerAssembly @Inject constructor(
    @param:ApplicationContext private val context: Context,
    private val api: TunesApi,
    private val caches: MediaCaches,
    private val sources: MediaDataSources,
    val settings: PlayerSettingsSource
) {
    /** A new player; the caller releases it. */
    fun newPlayer(): ExoPlayer = ExoPlayer.Builder(context)
        .setMediaSourceFactory(DefaultMediaSourceFactory(sources.playback))
        .setAudioAttributes(
            AudioAttributes.Builder()
                .setUsage(C.USAGE_MEDIA)
                .setContentType(C.AUDIO_CONTENT_TYPE_MUSIC)
                .build(),
            true
        )
        .setHandleAudioBecomingNoisy(true)
        .setWakeMode(C.WAKE_MODE_NETWORK)
        .build()

    /** The engine of [player], working in [scope] (the main thread). */
    fun newEngine(player: ExoPlayer, scope: CoroutineScope): PlaybackEngine = PlaybackEngine(
        player = player,
        api = api,
        prefetcher = Prefetcher(
            PrefetchPlanner(
                lookahead = PrefetchPlanner.UPCOMING_SONGS,
                preloadBytes = CachePolicy.PRELOAD_BYTES
            ),
            MediaPrefetchTarget(api, caches, sources),
            scope
        ),
        poller = StatusPoller(api::trackStatus),
        janitor = CacheJanitor(MediaCacheView(caches.play)),
        gains = ReplayGainSource(api),
        scope = scope,
        io = Dispatchers.IO
    )

    /** Applies a new play cache size. */
    fun resizeCache(cacheSizeMb: Int) = caches.resizePlayCache(cacheSizeMb)

    /** Loads artwork for the notification through the authenticated client. */
    fun bitmapLoader(): BitmapLoader =
        DataSourceBitmapLoader.Builder(context).setDataSourceFactory(sources.http).build()

    /**
     * Resolves the stream URL of every item a controller adds (see [MediaItems.resolve]). Only the
     * app itself and controllers Media3 marks as trusted may change the queue; any other app gets
     * Media3's restricted (untrusted) command set without the queue commands, so it cannot make
     * the server download anything.
     * "Trusted" means the system (notification, Bluetooth, headsets), apps holding
     * MEDIA_CONTENT_CONTROL **and enabled notification-listener apps**: the user granted those
     * access to every notification, so they also count as trusted here.
     */
    fun sessionCallback(): MediaSession.Callback = object : MediaSession.Callback {
        override fun onConnect(
            session: MediaSession,
            controller: MediaSession.ControllerInfo
        ): MediaSession.ConnectionResult {
            // The app itself: same package and same uid (a package name alone can be claimed).
            val app = controller.packageName == context.packageName &&
                controller.uid == Process.myUid()
            val commands = if (app || controller.isTrusted) {
                MediaSession.ConnectionResult.DEFAULT_PLAYER_COMMANDS
            } else {
                MediaSession.ConnectionResult.DEFAULT_UNTRUSTED_PLAYER_COMMANDS
                    .buildUpon()
                    .removeAll(Player.COMMAND_SET_MEDIA_ITEM, Player.COMMAND_CHANGE_MEDIA_ITEMS)
                    .build()
            }
            return MediaSession.ConnectionResult.AcceptedResultBuilder(session, controller)
                .setAvailablePlayerCommands(commands)
                .build()
        }

        override fun onAddMediaItems(
            mediaSession: MediaSession,
            controller: MediaSession.ControllerInfo,
            mediaItems: List<MediaItem>
        ): ListenableFuture<List<MediaItem>> =
            Futures.immediateFuture(mediaItems.map { MediaItems.resolve(it, api) })
    }
}
