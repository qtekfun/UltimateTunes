// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.radio

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.model.StationTile
import com.qtekfun.ultimatetunes.ui.model.loadStateOf
import com.qtekfun.ultimatetunes.ui.model.toTile
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/** The stations of the Radio tab. */
data class RadioContent(
    /** The user's favourite stations, shown large. */
    val featured: List<StationTile>,
    /** One station per most-played song ("Stations from your favourite songs"). */
    val fromSongs: List<StationTile>
) {
    val isEmpty: Boolean get() = featured.isEmpty() && fromSongs.isEmpty()
}

/**
 * The Radio tab (RF-06, RF-11): favourite stations and stations seeded from the most played
 * songs, both from `GET /ut/v1/listen-now`. A station opens [StationViewModel].
 */
@HiltViewModel
class RadioViewModel @Inject constructor(private val api: TunesApi) : ViewModel() {
    private val mutableState = MutableStateFlow<LoadState<RadioContent>>(LoadState.Loading)
    val state: StateFlow<LoadState<RadioContent>> = mutableState.asStateFlow()

    private var loading: Job? = null

    init {
        load()
    }

    fun load() {
        if (loading?.isActive == true) return
        if (mutableState.value !is LoadState.Ready) mutableState.value = LoadState.Loading
        loading = viewModelScope.launch {
            mutableState.value = loadStateOf(api.listenNow()) { listenNow ->
                val featured = listenNow.favouriteRadios.map { it.toTile(api) }
                val featuredSeeds = featured.map { it.seedId }.toSet()
                RadioContent(
                    featured = featured,
                    fromSongs = listenNow.mostPlayed
                        .filter { it.id !in featuredSeeds }
                        .map { track ->
                            val tile = track.toTile(api)
                            StationTile(
                                seedId = tile.id,
                                title = tile.title,
                                subtitle = tile.artist,
                                coverUrl = tile.coverUrl
                            )
                        }
                )
            }
        }
    }
}
