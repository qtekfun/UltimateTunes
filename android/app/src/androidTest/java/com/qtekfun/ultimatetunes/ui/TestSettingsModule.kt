// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui

import com.qtekfun.ultimatetunes.ui.di.SettingsModule
import com.qtekfun.ultimatetunes.ui.settings.AppPrefsStore
import com.qtekfun.ultimatetunes.ui.settings.PlaybackSettings
import com.qtekfun.ultimatetunes.ui.settings.PlaybackSettingsStore
import dagger.Module
import dagger.Provides
import dagger.hilt.components.SingletonComponent
import dagger.hilt.testing.TestInstallIn
import javax.inject.Singleton
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update

/**
 * UI tests keep settings in memory, so they never change the choices of the app installed on the
 * author's phone. The notification question starts answered; FeaturesTest asks it on purpose.
 */
@Module
@TestInstallIn(components = [SingletonComponent::class], replaces = [SettingsModule::class])
object TestSettingsModule {
    @Provides
    @Singleton
    fun playbackSettings(): PlaybackSettingsStore = MemoryPlaybackSettings()

    @Provides
    @Singleton
    fun appPrefs(): AppPrefsStore = MemoryAppPrefs()
}

class MemoryPlaybackSettings : PlaybackSettingsStore {
    override val settings = MutableStateFlow(PlaybackSettings())

    override suspend fun setCacheSizeMb(value: Int) = settings.update {
        it.copy(cacheSizeMb = value)
    }

    override suspend fun setOfflineOnly(value: Boolean) =
        settings.update { it.copy(offlineOnly = value) }

    override suspend fun setDownloadOnWifiOnly(value: Boolean) =
        settings.update { it.copy(downloadOnWifiOnly = value) }

    override suspend fun setLibraryOffline(value: Boolean) =
        settings.update { it.copy(libraryOffline = value) }

    override suspend fun setLibraryOfflineLimitMb(value: Int) =
        settings.update { it.copy(libraryOfflineLimitMb = value) }
}

class MemoryAppPrefs : AppPrefsStore {
    override val exportFolder = MutableStateFlow<String?>(null)
    override val notificationsAsked = MutableStateFlow(true)

    override suspend fun setExportFolder(uri: String?) {
        exportFolder.value = uri
    }

    override suspend fun setNotificationsAsked(value: Boolean) {
        notificationsAsked.value = value
    }
}
