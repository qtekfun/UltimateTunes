// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.library

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.ui.model.ArtistTile
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.model.loadStateOf
import com.qtekfun.ultimatetunes.ui.model.toTile
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/** The artists under one letter of the index. */
data class ArtistSection(val letter: String, val artists: List<ArtistTile>)

/** Library › Artists: the server's artist index (`getArtists`), letter by letter. */
@HiltViewModel
class ArtistsViewModel @Inject constructor(private val api: TunesApi) : ViewModel() {
    private val mutableState = MutableStateFlow<LoadState<List<ArtistSection>>>(LoadState.Loading)
    val state: StateFlow<LoadState<List<ArtistSection>>> = mutableState.asStateFlow()

    private var loading: Job? = null

    init {
        load()
    }

    fun load() {
        if (loading?.isActive == true) return
        mutableState.value = LoadState.Loading
        loading = viewModelScope.launch {
            mutableState.value = loadStateOf(api.artists()) { indexes ->
                indexes.index
                    .filter { it.artist.isNotEmpty() }
                    .map { index -> ArtistSection(index.name, index.artist.map { it.toTile(api) }) }
            }
        }
    }
}
