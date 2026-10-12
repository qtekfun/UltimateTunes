// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

@file:OptIn(UnstableApi::class)

package com.qtekfun.ultimatetunes.core.player.di

import android.content.Context
import androidx.annotation.OptIn
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import androidx.datastore.preferences.preferencesDataStoreFile
import androidx.media3.common.util.UnstableApi
import androidx.media3.database.DatabaseProvider
import androidx.media3.database.StandaloneDatabaseProvider
import androidx.media3.datasource.cache.NoOpCacheEvictor
import androidx.media3.datasource.cache.SimpleCache
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.di.TunesHttpClient
import com.qtekfun.ultimatetunes.core.player.cache.AdjustableLruEvictor
import com.qtekfun.ultimatetunes.core.player.cache.CachePolicy
import com.qtekfun.ultimatetunes.core.player.media.MediaCaches
import com.qtekfun.ultimatetunes.core.player.media.MediaDataSources
import com.qtekfun.ultimatetunes.core.player.offline.DataStoreOfflineSelection
import com.qtekfun.ultimatetunes.core.player.offline.OfflineDownloads
import com.qtekfun.ultimatetunes.core.player.offline.OfflineSelectionStore
import com.qtekfun.ultimatetunes.core.player.offline.OfflineSyncer
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import java.io.File
import javax.inject.Singleton
import okhttp3.OkHttpClient

/**
 * The player's singletons. Both caches live in `noBackupFilesDir` (never backed up, never cleared
 * by the system like `cacheDir`); one `SimpleCache` per folder and process, hence singletons.
 */
@Module
@InstallIn(SingletonComponent::class)
object PlayerModule {
    @Provides
    @Singleton
    fun databaseProvider(@ApplicationContext context: Context): DatabaseProvider =
        StandaloneDatabaseProvider(context)

    @Provides
    @Singleton
    fun mediaCaches(@ApplicationContext context: Context, database: DatabaseProvider): MediaCaches {
        // Settings resize it as soon as the player starts (PlayerSettings.cacheSizeMb).
        val evictor = AdjustableLruEvictor(CachePolicy.maxBytes(CachePolicy.DEFAULT_CACHE_MB))
        return MediaCaches(
            play = SimpleCache(File(context.noBackupFilesDir, "media-cache"), evictor, database),
            evictor = evictor,
            downloads = SimpleCache(
                File(context.noBackupFilesDir, "offline"),
                NoOpCacheEvictor(),
                database
            )
        )
    }

    @Provides
    @Singleton
    fun mediaDataSources(
        @TunesHttpClient client: OkHttpClient,
        caches: MediaCaches
    ): MediaDataSources = MediaDataSources(client, caches)

    @Provides
    @Singleton
    fun offlineSelection(@ApplicationContext context: Context): OfflineSelectionStore =
        DataStoreOfflineSelection(
            PreferenceDataStoreFactory.create {
                context.preferencesDataStoreFile("offline_selection")
            }
        )

    @Provides
    fun offlineSyncer(
        api: TunesApi,
        store: OfflineSelectionStore,
        downloads: OfflineDownloads
    ): OfflineSyncer = OfflineSyncer(api, store, downloads)
}
