// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.search

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.availability.PhoneAvailability
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.library.LibraryRepository
import com.qtekfun.ultimatetunes.ui.model.AlbumTile
import com.qtekfun.ultimatetunes.ui.model.ArtistTile
import com.qtekfun.ultimatetunes.ui.model.LoadError
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import com.qtekfun.ultimatetunes.ui.model.loadStateOf
import com.qtekfun.ultimatetunes.ui.model.toTile
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
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

/** Why the results are only the phone's. */
enum class SearchNotice { NO_CONNECTION, SERVER_UNREACHABLE, OFFLINE_MODE }

/** What the Search tab shows. */
data class SearchUiState(
    val query: String = "",
    /** Null before the first search (and when the field is cleared). */
    val results: LoadState<SearchContent>? = null,
    /** True while a search runs; the previous results stay on screen meanwhile. */
    val searching: Boolean = false,
    /** Set when the results come from the phone alone. */
    val notice: SearchNotice? = null
)

/**
 * The Search tab (RF-03, RF-11, RF-12): the phone's catalog at once, then the server's list
 * merging the library and YouTube Music (`GET /ut/v1/search`). With no connection, in offline mode
 * or when the server does not answer, the phone's results stay and [SearchUiState.notice] says why.
 * Typing searches after a short pause; the keyboard's search key at once.
 * A search is remembered when it is submitted or one of its results opened.
 */
@HiltViewModel
class SearchViewModel @Inject constructor(
    private val api: TunesApi,
    private val library: LibraryRepository,
    private val phone: PhoneAvailability,
    private val recents: RecentSearchesStore
) : ViewModel() {
    private val mutableState = MutableStateFlow(SearchUiState())
    val state: StateFlow<SearchUiState> = mutableState.asStateFlow()

    /** Newest first; shown while the field is empty. */
    val recentSearches: StateFlow<List<String>> =
        recents.searches.stateIn(viewModelScope, SharingStarted.Eagerly, emptyList())

    private var searchJob: Job? = null

    init {
        // The connection coming or going, or offline mode switching, changes where to search.
        viewModelScope.launch {
            phone.availability.map { it.online to it.offlineMode }
                .distinctUntilChanged()
                .drop(1)
                .collect { search() }
        }
    }

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

    /** The keyboard's search key: searches at once and remembers the query. */
    fun submit() {
        remember()
        search()
    }

    /** One of the results was opened or played. */
    fun remember() {
        val query = mutableState.value.query
        viewModelScope.launch { recents.add(query) }
    }

    fun runRecent(query: String) {
        mutableState.update { it.copy(query = query) }
        submit()
    }

    fun removeRecent(query: String) {
        viewModelScope.launch { recents.remove(query) }
    }

    fun clearRecents() {
        viewModelScope.launch { recents.clear() }
    }

    /** Searches the current query now (retry, a change of connection). */
    fun search() {
        val query = mutableState.value.query.trim()
        if (query.isEmpty()) return
        searchJob?.cancel()
        searchJob = viewModelScope.launch { run(query) }
    }

    private suspend fun run(query: String) {
        mutableState.update { it.copy(searching = true) }
        val local = searchPhone(query)
        val now = phone.availability.value
        if (now.onlyPhone) {
            val notice =
                if (now.online) SearchNotice.OFFLINE_MODE else SearchNotice.NO_CONNECTION
            show(LoadState.Ready(local), notice)
            return
        }
        if (!local.isEmpty) {
            mutableState.update {
                it.copy(results = LoadState.Ready(local), notice = null)
            }
        }
        val server = loadStateOf(api.search(query)) { found ->
            SearchContent(
                artists = found.artists.map { it.toTile(api) },
                albums = found.albums.map { it.toTile(api) },
                tracks = found.tracks.map { it.toTile(api) }
            )
        }
        // No answer at all, or an error (a proxy with the server down) while the phone has some.
        val failed = (server as? LoadState.Failed)?.error
        if (failed == LoadError.NETWORK || (failed == LoadError.SERVER && !local.isEmpty)) {
            show(LoadState.Ready(local), SearchNotice.SERVER_UNREACHABLE)
        } else {
            show(server, null)
        }
    }

    /** The phone's matches, what can play now first, cut to what a list is worth showing. */
    private suspend fun searchPhone(query: String): SearchContent {
        val found = library.search(query)
        val now = phone.availability.value
        return SearchContent(
            artists = found.artists.sortedByDescending { now.canPlayArtist(it.id) }
                .take(MAX_PHONE_ARTISTS)
                .map { it.toTile(api) },
            albums = found.albums.sortedByDescending { now.canPlayAlbum(it.id) }
                .take(MAX_PHONE_ALBUMS)
                .map { it.toTile(api) },
            tracks = found.songs.sortedByDescending { now.canPlay(it.id) }
                .take(MAX_PHONE_SONGS)
                .map { it.toTile(api) }
        )
    }

    private fun show(results: LoadState<SearchContent>, notice: SearchNotice?) {
        mutableState.update { it.copy(results = results, searching = false, notice = notice) }
    }

    companion object {
        /** Pause after the last keystroke before searching. */
        const val DEBOUNCE_MS = 350L

        private const val MAX_PHONE_ARTISTS = 30
        private const val MAX_PHONE_ALBUMS = 50
        private const val MAX_PHONE_SONGS = 200
    }
}
