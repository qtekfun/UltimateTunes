// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.radio

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.model.SongId
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

/** A station's queue: the seed first, then what the radio found. */
data class StationContent(val seed: TrackTile, val upNext: List<TrackTile>) {
    /** What playing the station queues, seed first. */
    val queue: List<TrackTile> get() = listOf(seed) + upNext
}

/** A radio station (`GET /ut/v1/radio?seed=<id>`), opened from Radio or Listen Now. */
@HiltViewModel
class StationViewModel @Inject constructor(
    savedStateHandle: SavedStateHandle,
    private val api: TunesApi
) : ViewModel() {
    private val seed = SongId(checkNotNull(savedStateHandle.get<String>(ARG_SEED)))

    private val mutableState = MutableStateFlow<LoadState<StationContent>>(LoadState.Loading)
    val state: StateFlow<LoadState<StationContent>> = mutableState.asStateFlow()

    private var loading: Job? = null

    init {
        load()
    }

    fun load() {
        if (loading?.isActive == true) return
        mutableState.value = LoadState.Loading
        loading = viewModelScope.launch {
            mutableState.value = loadStateOf(api.radio(seed, QUEUE_LENGTH)) { radio ->
                StationContent(
                    seed = radio.seed.toTile(api),
                    upNext = radio.items.map { it.toTile(api) }
                )
            }
        }
    }

    companion object {
        /** Navigation argument: the seed song id. */
        const val ARG_SEED = "seedId"

        /** How many songs a station queues at first. */
        const val QUEUE_LENGTH = 50
    }
}
