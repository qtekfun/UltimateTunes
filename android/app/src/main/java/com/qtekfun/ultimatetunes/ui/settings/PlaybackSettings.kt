// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.settings

import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

/**
 * The device's playback and offline choices (RF-12), shown in Settings. The player (PLAN T17)
 * reads them: the size of Media3's `SimpleCache`, whether only cached and downloaded music is
 * offered, whether offline downloads wait for Wi-Fi, and whether the whole library is kept offline
 * (with its limit).
 */
data class PlaybackSettings(
    val cacheSizeMb: Int = DEFAULT_CACHE_MB,
    val offlineOnly: Boolean = false,
    val downloadOnWifiOnly: Boolean = true,
    /** "Keep my whole library offline" (RF-12). */
    val libraryOffline: Boolean = false,
    val libraryOfflineLimitMb: Int = DEFAULT_LIBRARY_OFFLINE_MB
) {
    companion object {
        /** 2 GB, the default of RF-12. */
        const val DEFAULT_CACHE_MB = 2048

        /** The cache sizes Settings offers, in MB. */
        val CACHE_SIZES_MB = listOf(512, 1024, 2048, 5120, 10240)

        /** 10 GB, the default limit of the whole library kept offline. */
        const val DEFAULT_LIBRARY_OFFLINE_MB = 10240

        /** The limits Settings offers for it, in MB. */
        val LIBRARY_OFFLINE_LIMITS_MB = listOf(2048, 5120, 10240, 20480, 51200, 102400)
    }
}

/** Where [PlaybackSettings] are kept. */
interface PlaybackSettingsStore {
    val settings: Flow<PlaybackSettings>

    suspend fun setCacheSizeMb(value: Int)

    suspend fun setOfflineOnly(value: Boolean)

    suspend fun setDownloadOnWifiOnly(value: Boolean)

    suspend fun setLibraryOffline(value: Boolean)

    suspend fun setLibraryOfflineLimitMb(value: Int)
}

/** [PlaybackSettingsStore] in a Preferences DataStore. */
class DataStorePlaybackSettings(private val dataStore: DataStore<Preferences>) :
    PlaybackSettingsStore {
    override val settings: Flow<PlaybackSettings> = dataStore.data.map { prefs ->
        PlaybackSettings(
            cacheSizeMb = prefs[CACHE_SIZE_MB] ?: PlaybackSettings.DEFAULT_CACHE_MB,
            offlineOnly = prefs[OFFLINE_ONLY] ?: false,
            downloadOnWifiOnly = prefs[WIFI_ONLY] ?: true,
            libraryOffline = prefs[LIBRARY_OFFLINE] ?: false,
            libraryOfflineLimitMb = prefs[LIBRARY_OFFLINE_LIMIT_MB]
                ?: PlaybackSettings.DEFAULT_LIBRARY_OFFLINE_MB
        )
    }

    override suspend fun setCacheSizeMb(value: Int) {
        dataStore.edit { it[CACHE_SIZE_MB] = value }
    }

    override suspend fun setOfflineOnly(value: Boolean) {
        dataStore.edit { it[OFFLINE_ONLY] = value }
    }

    override suspend fun setDownloadOnWifiOnly(value: Boolean) {
        dataStore.edit { it[WIFI_ONLY] = value }
    }

    override suspend fun setLibraryOffline(value: Boolean) {
        dataStore.edit { it[LIBRARY_OFFLINE] = value }
    }

    override suspend fun setLibraryOfflineLimitMb(value: Int) {
        dataStore.edit { it[LIBRARY_OFFLINE_LIMIT_MB] = value }
    }

    private companion object {
        val CACHE_SIZE_MB = intPreferencesKey("cache_size_mb")
        val OFFLINE_ONLY = booleanPreferencesKey("offline_only")
        val WIFI_ONLY = booleanPreferencesKey("download_on_wifi_only")
        val LIBRARY_OFFLINE = booleanPreferencesKey("library_offline")
        val LIBRARY_OFFLINE_LIMIT_MB = intPreferencesKey("library_offline_limit_mb")
    }
}
