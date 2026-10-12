// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.settings

import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

/**
 * Small choices of this device that are not playback settings: the export folder (RF-14, a tree
 * URI the user granted with the system picker) and whether the notification permission was
 * already explained (RF-13).
 */
interface AppPrefsStore {
    val exportFolder: Flow<String?>

    val notificationsAsked: Flow<Boolean>

    suspend fun setExportFolder(uri: String?)

    suspend fun setNotificationsAsked(value: Boolean)
}

/** [AppPrefsStore] in a Preferences DataStore. */
class DataStoreAppPrefs(private val dataStore: DataStore<Preferences>) : AppPrefsStore {
    override val exportFolder: Flow<String?> = dataStore.data.map { it[EXPORT_FOLDER] }

    override val notificationsAsked: Flow<Boolean> =
        dataStore.data.map { it[NOTIFICATIONS_ASKED] ?: false }

    override suspend fun setExportFolder(uri: String?) {
        dataStore.edit { if (uri == null) it.remove(EXPORT_FOLDER) else it[EXPORT_FOLDER] = uri }
    }

    override suspend fun setNotificationsAsked(value: Boolean) {
        dataStore.edit { it[NOTIFICATIONS_ASKED] = value }
    }

    private companion object {
        val EXPORT_FOLDER = stringPreferencesKey("export_folder")
        val NOTIFICATIONS_ASKED = booleanPreferencesKey("notifications_asked")
    }
}
