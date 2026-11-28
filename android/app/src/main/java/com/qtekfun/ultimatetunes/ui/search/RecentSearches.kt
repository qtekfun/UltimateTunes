// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.search

import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.MutablePreferences
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map

/** What was searched on this phone, newest first; it belongs to one server. */
interface RecentSearchesStore {
    val searches: Flow<List<String>>

    /** Puts [query] first; one that only differs in case moves up instead of repeating. */
    suspend fun add(query: String)

    suspend fun remove(query: String)

    suspend fun clear()

    /** The app is connected to [server]: forgets the searches made on another one. */
    suspend fun serverConnected(server: String)
}

/** [RecentSearchesStore] in a Preferences DataStore, one search per line. */
class DataStoreRecentSearches(private val dataStore: DataStore<Preferences>) :
    RecentSearchesStore {
    override val searches: Flow<List<String>> =
        dataStore.data.map { it.queries() }.distinctUntilChanged()

    override suspend fun add(query: String) {
        val clean = query.replace(WHITESPACE, " ").trim()
        if (clean.isEmpty()) return
        dataStore.edit { prefs ->
            val others = prefs.queries().filterNot { it.equals(clean, ignoreCase = true) }
            prefs.store(listOf(clean) + others.take(MAX_SEARCHES - 1))
        }
    }

    override suspend fun remove(query: String) {
        dataStore.edit { it.store(it.queries() - query) }
    }

    override suspend fun clear() {
        dataStore.edit { it.remove(QUERIES) }
    }

    override suspend fun serverConnected(server: String) {
        dataStore.edit { prefs ->
            val before = prefs[SERVER]
            if (before != null && before != server) prefs.remove(QUERIES)
            prefs[SERVER] = server
        }
    }

    private fun Preferences.queries(): List<String> =
        this[QUERIES]?.split('\n')?.filter { it.isNotEmpty() }.orEmpty()

    private fun MutablePreferences.store(queries: List<String>) {
        this[QUERIES] = queries.joinToString("\n")
    }

    companion object {
        const val MAX_SEARCHES = 10

        private val WHITESPACE = Regex("\\s+")
        private val QUERIES = stringPreferencesKey("queries")
        private val SERVER = stringPreferencesKey("server")
    }
}
