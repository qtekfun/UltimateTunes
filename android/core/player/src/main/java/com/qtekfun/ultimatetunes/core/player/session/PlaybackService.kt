// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

@file:OptIn(UnstableApi::class)

package com.qtekfun.ultimatetunes.core.player.session

import android.app.PendingIntent
import android.content.Intent
import androidx.annotation.OptIn
import androidx.media3.common.util.UnstableApi
import androidx.media3.session.MediaSession
import androidx.media3.session.MediaSessionService
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch

/**
 * The media session service (RF-11, RF-12): it owns the player, so music keeps playing with the
 * app in the background, shows the playback notification and answers media buttons. The app
 * talks to it through a `MediaController`.
 */
@AndroidEntryPoint
class PlaybackService : MediaSessionService() {
    @Inject
    lateinit var assembly: PlayerAssembly

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var session: MediaSession? = null
    private var engine: PlaybackEngine? = null

    override fun onCreate() {
        super.onCreate()
        val player = assembly.newPlayer()
        val engine = assembly.newEngine(player, scope).also { this.engine = it }
        session = MediaSession.Builder(this, player)
            .setCallback(assembly.sessionCallback())
            .setBitmapLoader(assembly.bitmapLoader())
            .apply { launchIntent()?.let(::setSessionActivity) }
            .build()
        engine.start()
        scope.launch {
            assembly.settings.settings.collect { engine.offlineOnly = it.offlineOnly }
        }
        scope.launch {
            assembly.settings.settings.map { it.cacheSizeMb }.distinctUntilChanged()
                .collect(assembly::resizeCache)
        }
    }

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaSession? = session

    override fun onTaskRemoved(rootIntent: Intent?) {
        // Swiping the app away while paused ends the service; while playing, music goes on.
        if (!isPlaybackOngoing) pauseAllPlayersAndStopSelf()
    }

    override fun onDestroy() {
        engine?.release()
        session?.run {
            player.release()
            release()
        }
        session = null
        scope.cancel()
        super.onDestroy()
    }

    /** Opens the app from the notification. */
    private fun launchIntent(): PendingIntent? =
        packageManager.getLaunchIntentForPackage(packageName)?.let {
            PendingIntent.getActivity(
                this,
                0,
                it,
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
            )
        }
}
