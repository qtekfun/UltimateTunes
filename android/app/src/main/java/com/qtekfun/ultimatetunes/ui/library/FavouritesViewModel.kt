// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.library

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.library.CatalogSync
import com.qtekfun.ultimatetunes.core.library.LibraryRepository
import com.qtekfun.ultimatetunes.ui.model.AlbumTile
import com.qtekfun.ultimatetunes.ui.model.ArtistTile
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.model.Refresher
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import com.qtekfun.ultimatetunes.ui.model.contentState
import com.qtekfun.ultimatetunes.ui.model.syncError
import com.qtekfun.ultimatetunes.ui.model.toTile
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn

/** The user's favourites (RF-09). */
data class FavouritesContent(
    val songs: List<TrackTile>,
    val albums: List<AlbumTile>,
    val artists: List<ArtistTile>
) {
    val isEmpty: Boolean get() = songs.isEmpty() && albums.isEmpty() && artists.isEmpty()
}

/** Library › Favourites: starred songs, albums and artists, as the local catalog has them. */
@HiltViewModel
class FavouritesViewModel @Inject constructor(
    api: TunesApi,
    repository: LibraryRepository,
    private val sync: CatalogSync
) : ViewModel() {
    val refresher = Refresher(viewModelScope) { sync.syncError() }

    private val favourites = combine(
        repository.favouriteSongs(),
        repository.favouriteAlbums(),
        repository.favouriteArtists()
    ) { songs, albums, artists ->
        FavouritesContent(
            songs = songs.map { it.toTile(api) },
            albums = albums.map { it.toTile(api) },
            artists = artists.map { it.toTile(api) }
        )
    }

    val state: StateFlow<LoadState<FavouritesContent>> =
        combine(repository.syncState, favourites) { synced, content ->
            synced.contentState { content }
        }.stateIn(
            viewModelScope,
            SharingStarted.WhileSubscribed(STOP_TIMEOUT_MS),
            LoadState.Loading
        )

    private companion object {
        const val STOP_TIMEOUT_MS = 5_000L
    }
}
