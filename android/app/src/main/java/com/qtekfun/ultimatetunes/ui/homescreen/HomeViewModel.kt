// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.homescreen

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.library.CatalogSync
import com.qtekfun.ultimatetunes.core.library.LibraryRepository
import com.qtekfun.ultimatetunes.ui.model.AlbumTile
import com.qtekfun.ultimatetunes.ui.model.LoadError
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.model.Refresher
import com.qtekfun.ultimatetunes.ui.model.StationTile
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import com.qtekfun.ultimatetunes.ui.model.contentState
import com.qtekfun.ultimatetunes.ui.model.syncError
import com.qtekfun.ultimatetunes.ui.model.toLoadError
import com.qtekfun.ultimatetunes.ui.model.toTile
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

/** The Home shelves that come from the catalog, and the stations. */
data class HomeContent(
    /** What was played last (the albums added last while nothing was), for quick access. */
    val quickAccess: List<AlbumTile>,
    val recentlyAdded: List<AlbumTile>,
    val mostPlayed: List<TrackTile>,
    /** The user's favourite stations, then one per most played song. */
    val stations: List<StationTile>
) {
    val isEmpty: Boolean
        get() = quickAccess.isEmpty() && recentlyAdded.isEmpty() &&
            mostPlayed.isEmpty() && stations.isEmpty()
}

/** What the Home tab shows. */
data class HomeUiState(
    val content: LoadState<HomeContent> = LoadState.Loading,
    /** Why the catalog is behind the server; null when the last sync worked. */
    val syncError: LoadError? = null
)

/**
 * The Home tab (RF-11): recently played, top songs and recent additions from the local catalog,
 * so they show with no connection, and the stations. The favourite stations are the server's
 * (`GET /ut/v1/listen-now`); what was read of them stays when a refresh fails.
 */
@HiltViewModel
class HomeViewModel @Inject constructor(
    private val api: TunesApi,
    repository: LibraryRepository,
    private val sync: CatalogSync
) : ViewModel() {
    private val favouriteStations = MutableStateFlow(emptyList<StationTile>())

    val refresher = Refresher(viewModelScope) {
        val stationsError = loadStations()
        sync.syncError() ?: stationsError
    }

    private val shelves = combine(
        repository.recentlyPlayedAlbums(QUICK_ALBUMS),
        repository.recentlyAddedAlbums(RECENT_ALBUMS),
        repository.mostPlayedSongs(TOP_SONGS),
        favouriteStations
    ) { played, added, top, favourites ->
        val recentlyAdded = added.map { it.toTile(api) }
        val mostPlayed = top.map { it.toTile(api) }
        val seeds = favourites.mapTo(HashSet()) { it.seedId }
        HomeContent(
            quickAccess = played.map { it.toTile(api) }
                .ifEmpty { recentlyAdded.take(QUICK_ALBUMS) },
            recentlyAdded = recentlyAdded,
            mostPlayed = mostPlayed,
            stations = favourites + mostPlayed.filterNot { it.id in seeds }
                .map { StationTile(it.id, it.title, it.artist, it.coverUrl) }
        )
    }

    val state: StateFlow<HomeUiState> = combine(repository.syncState, shelves) { sync, content ->
        HomeUiState(sync.contentState { content }, sync.error?.toLoadError())
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(STOP_TIMEOUT_MS), HomeUiState())

    init {
        viewModelScope.launch { loadStations() }
    }

    /** Reads the favourite stations; why that failed, or null. */
    private suspend fun loadStations(): LoadError? = when (val result = api.listenNow()) {
        is TunesResult.Success -> {
            favouriteStations.value = result.value.favouriteRadios.map { it.toTile(api) }
            null
        }

        is TunesResult.Failure -> result.toLoadError()
    }

    companion object {
        /** Albums in the quick access grid, beside the favourites. */
        const val QUICK_ALBUMS = 5
        const val RECENT_ALBUMS = 12
        const val TOP_SONGS = 10
        private const val STOP_TIMEOUT_MS = 5_000L
    }
}
