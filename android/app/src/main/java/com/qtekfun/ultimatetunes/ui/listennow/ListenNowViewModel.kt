// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.listennow

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.ui.model.AlbumTile
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.model.StationTile
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

/** The Listen Now shelves, ready to show. */
data class ListenNowContent(
    val recentlyPlayed: List<AlbumTile>,
    val recentlyAdded: List<AlbumTile>,
    val mostPlayed: List<TrackTile>,
    val stations: List<StationTile>
) {
    val isEmpty: Boolean
        get() = recentlyPlayed.isEmpty() && recentlyAdded.isEmpty() &&
            mostPlayed.isEmpty() && stations.isEmpty()
}

/** The Listen Now tab (RF-11): `GET /ut/v1/listen-now` as shelves. */
@HiltViewModel
class ListenNowViewModel @Inject constructor(private val api: TunesApi) : ViewModel() {
    private val mutableState = MutableStateFlow<LoadState<ListenNowContent>>(LoadState.Loading)
    val state: StateFlow<LoadState<ListenNowContent>> = mutableState.asStateFlow()

    private var loading: Job? = null

    init {
        load()
    }

    /** Loads the shelves again (retry after an error, pull to refresh). */
    fun load() {
        if (loading?.isActive == true) return
        if (mutableState.value !is LoadState.Ready) mutableState.value = LoadState.Loading
        loading = viewModelScope.launch {
            mutableState.value = loadStateOf(api.listenNow()) { listenNow ->
                ListenNowContent(
                    recentlyPlayed = listenNow.recentlyPlayed.map { it.toTile(api) },
                    recentlyAdded = listenNow.recentlyAdded.map { it.toTile(api) },
                    mostPlayed = listenNow.mostPlayed.map { it.toTile(api) },
                    stations = listenNow.favouriteRadios.map { it.toTile(api) }
                )
            }
        }
    }
}
