// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.di

import android.content.Context
import androidx.datastore.core.handlers.ReplaceFileCorruptionHandler
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import androidx.datastore.preferences.core.emptyPreferences
import androidx.datastore.preferences.preferencesDataStoreFile
import com.qtekfun.ultimatetunes.playback.DownloadsOfflineLibrary
import com.qtekfun.ultimatetunes.ui.actions.Exports
import com.qtekfun.ultimatetunes.ui.actions.SafExports
import com.qtekfun.ultimatetunes.ui.library.OfflineLibrary
import com.qtekfun.ultimatetunes.ui.search.DataStoreRecentSearches
import com.qtekfun.ultimatetunes.ui.search.RecentSearchesStore
import com.qtekfun.ultimatetunes.ui.settings.AppPrefsStore
import com.qtekfun.ultimatetunes.ui.settings.DataStoreAppPrefs
import com.qtekfun.ultimatetunes.ui.settings.DataStorePlaybackSettings
import com.qtekfun.ultimatetunes.ui.settings.PlaybackSettingsStore
import dagger.Binds
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

    @Provides
    @Singleton
    fun appPrefs(@ApplicationContext context: Context): AppPrefsStore = DataStoreAppPrefs(
        PreferenceDataStoreFactory.create { context.preferencesDataStoreFile("app_prefs") }
    )

    @Provides
    @Singleton
    fun recentSearches(@ApplicationContext context: Context): RecentSearchesStore =
        DataStoreRecentSearches(
            PreferenceDataStoreFactory.create(
                // Losing the history beats failing on a damaged file.
                corruptionHandler = ReplaceFileCorruptionHandler { emptyPreferences() }
            ) { context.preferencesDataStoreFile("recent_searches") }
        )
}

/** The Library's Downloads list and the export to the phone, from the player (PLAN T17/T18). */
@Module
@InstallIn(SingletonComponent::class)
interface OfflineLibraryModule {
    @Binds
    fun offlineLibrary(impl: DownloadsOfflineLibrary): OfflineLibrary

    @Binds
    fun exports(impl: SafExports): Exports
}
