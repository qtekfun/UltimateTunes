// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.offline

import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import kotlinx.serialization.json.Json

/** Where the [OfflineSelection] is kept. */
interface OfflineSelectionStore {
    val selection: Flow<OfflineSelection>

    /** Changes the selection atomically. */
    suspend fun update(transform: (OfflineSelection) -> OfflineSelection)
}

/** [OfflineSelectionStore] as JSON in a Preferences DataStore. */
class DataStoreOfflineSelection(private val dataStore: DataStore<Preferences>) :
    OfflineSelectionStore {
    override val selection: Flow<OfflineSelection> = dataStore.data.map { decode(it[KEY]) }

    override suspend fun update(transform: (OfflineSelection) -> OfflineSelection) {
        dataStore.edit { prefs -> prefs[KEY] = JSON.encodeToString(transform(decode(prefs[KEY]))) }
    }

    private fun decode(text: String?): OfflineSelection = text?.let {
        try {
            JSON.decodeFromString<OfflineSelection>(it)
        } catch (ignored: IllegalArgumentException) {
            // Unreadable (SerializationException is one): start over rather than crash.
            null
        }
    } ?: OfflineSelection()

    private companion object {
        val KEY = stringPreferencesKey("offline_selection")
        val JSON = Json { ignoreUnknownKeys = true }
    }
}
