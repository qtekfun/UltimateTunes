// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.library

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
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/** The user's favourites (RF-09). */
data class FavouritesContent(
    val songs: List<TrackTile>,
    val albums: List<AlbumTile>,
    val artists: List<ArtistTile>
) {
    val isEmpty: Boolean get() = songs.isEmpty() && albums.isEmpty() && artists.isEmpty()
}

/** Library › Favourites (`getStarred2`): starred songs, albums and artists. */
@HiltViewModel
class FavouritesViewModel @Inject constructor(private val api: TunesApi) : ViewModel() {
    private val mutableState = MutableStateFlow<LoadState<FavouritesContent>>(LoadState.Loading)
    val state: StateFlow<LoadState<FavouritesContent>> = mutableState.asStateFlow()

    private var loading: Job? = null

    /** Loads the favourites; called each time the screen shows, so changes made elsewhere appear. */
    fun load() {
        if (loading?.isActive == true) return
        if (mutableState.value !is LoadState.Ready) mutableState.value = LoadState.Loading
        loading = viewModelScope.launch {
            mutableState.value = loadStateOf(api.starred()) { starred ->
                FavouritesContent(
                    songs = starred.song.map { it.toTile(api) },
                    albums = starred.album.map { it.toTile(api) },
                    artists = starred.artist.map { it.toTile(api) }
                )
            }
        }
    }
}
