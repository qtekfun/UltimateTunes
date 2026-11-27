// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.availability

import android.content.Context
import com.qtekfun.ultimatetunes.core.player.session.PhonePlayback
import dagger.Binds
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import java.io.File
import javax.inject.Singleton

/** What plays with no connection, and the covers kept for it. */
@Module
@InstallIn(SingletonComponent::class)
interface AvailabilityModule {
    @Binds
    fun connectivity(device: DeviceConnectivity): Connectivity

    @Binds
    fun cachedSongs(media: MediaCachedSongs): CachedSongs

    @Binds
    fun phoneAvailability(source: AvailabilitySource): PhoneAvailability

    @Binds
    fun phonePlayback(source: AvailabilitySource): PhonePlayback

    companion object {
        /** Beside the downloads: never backed up, never cleared by the system. */
        @Provides
        @Singleton
        fun offlineCovers(@ApplicationContext context: Context): OfflineCovers =
            OfflineCovers(File(context.noBackupFilesDir, "offline-covers"))
    }
}
