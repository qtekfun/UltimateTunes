// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.di

import android.content.Context
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import androidx.datastore.preferences.preferencesDataStoreFile
import com.qtekfun.ultimatetunes.ui.library.NoOfflineDownloads
import com.qtekfun.ultimatetunes.ui.library.OfflineLibrary
import com.qtekfun.ultimatetunes.ui.settings.DataStorePlaybackSettings
import com.qtekfun.ultimatetunes.ui.settings.PlaybackSettingsStore
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object SettingsModule {
    /** One DataStore per file and process, hence a singleton. */
    @Provides
    @Singleton
    fun playbackSettings(@ApplicationContext context: Context): PlaybackSettingsStore =
        DataStorePlaybackSettings(
            PreferenceDataStoreFactory.create {
                context.preferencesDataStoreFile("playback_settings")
            }
        )
}

/** Offline downloads arrive with PLAN T17, which replaces this module with its own binding. */
@Module
@InstallIn(SingletonComponent::class)
object OfflineLibraryModule {
    @Provides
    fun offlineLibrary(): OfflineLibrary = NoOfflineDownloads
}
