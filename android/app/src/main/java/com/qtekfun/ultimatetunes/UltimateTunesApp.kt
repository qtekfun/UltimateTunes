// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes

import android.app.Application
import com.qtekfun.ultimatetunes.playback.ListeningSync
import com.qtekfun.ultimatetunes.playback.PlaybackStartup
import dagger.hilt.android.HiltAndroidApp
import javax.inject.Inject

@HiltAndroidApp
class UltimateTunesApp : Application() {
    /** Restores the saved server and key (Keystore work off the main thread) and keeps saving. */
    @Inject
    lateinit var playbackStartup: PlaybackStartup

    /** Play history and the play queue shared across devices (RF-09). */
    @Inject
    lateinit var listeningSync: ListeningSync

    override fun onCreate() {
        super.onCreate()
        playbackStartup.onAppCreate()
        listeningSync.start()
    }
}
