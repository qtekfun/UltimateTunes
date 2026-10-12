// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.search

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.ui.model.AlbumTile
import com.qtekfun.ultimatetunes.ui.model.ArtistTile
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import com.qtekfun.ultimatetunes.ui.model.loadStateOf
import com.qtekfun.ultimatetunes.ui.model.toTile
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** Search results in the server's order: library items first, then YouTube Music ones. */
data class SearchContent(
    val artists: List<ArtistTile>,
    val albums: List<AlbumTile>,
    val tracks: List<TrackTile>
) {
    val isEmpty: Boolean get() = artists.isEmpty() && albums.isEmpty() && tracks.isEmpty()
}

/** What the Search tab shows. */
data class SearchUiState(
    val query: String = "",
    /** Null before the first search (and when the field is cleared). */
    val results: LoadState<SearchContent>? = null,
    /** True while a search runs; the previous results stay on screen meanwhile. */
    val searching: Boolean = false
)

/**
 * The Search tab (RF-03, RF-11): one list merging the library and YouTube Music
 * (`GET /ut/v1/search`). Typing searches after a short pause; the keyboard's search key at once.
 */
@HiltViewModel
class SearchViewModel @Inject constructor(private val api: TunesApi) : ViewModel() {
    private val mutableState = MutableStateFlow(SearchUiState())
    val state: StateFlow<SearchUiState> = mutableState.asStateFlow()

    private var searchJob: Job? = null

    fun onQueryChange(query: String) {
        mutableState.update { it.copy(query = query) }
        searchJob?.cancel()
        if (query.isBlank()) {
            mutableState.value = SearchUiState(query = query)
            return
        }
        searchJob = viewModelScope.launch {
            delay(DEBOUNCE_MS)
            run(query.trim())
        }
    }

    /** Searches the current query now (keyboard search key, retry). */
    fun search() {
        val query = mutableState.value.query.trim()
        if (query.isEmpty()) return
        searchJob?.cancel()
        searchJob = viewModelScope.launch { run(query) }
    }

    private suspend fun run(query: String) {
        mutableState.update { it.copy(searching = true) }
        val result = api.search(query)
        val results = loadStateOf(result) { found ->
            SearchContent(
                artists = found.artists.map { it.toTile(api) },
                albums = found.albums.map { it.toTile(api) },
                tracks = found.tracks.map { it.toTile(api) }
            )
        }
        mutableState.update { it.copy(results = results, searching = false) }
    }

    companion object {
        /** Pause after the last keystroke before searching. */
        const val DEBOUNCE_MS = 350L
    }
}
