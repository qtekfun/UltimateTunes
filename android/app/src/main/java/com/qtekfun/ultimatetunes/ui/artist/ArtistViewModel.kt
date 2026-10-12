// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.artist

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.model.ArtistId
import com.qtekfun.ultimatetunes.ui.model.AlbumTile
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

/** An artist and their albums, newest first. */
data class ArtistContent(val artist: ArtistTile, val albums: List<AlbumTile>)

/** An artist (`getArtist`): library ones, or `ytartist:` ones answered from YouTube Music. */
@HiltViewModel
class ArtistViewModel @Inject constructor(
    savedStateHandle: SavedStateHandle,
    private val api: TunesApi
) : ViewModel() {
    private val id = ArtistId(checkNotNull(savedStateHandle.get<String>(ARG_ID)))

    private val mutableState = MutableStateFlow<LoadState<ArtistContent>>(LoadState.Loading)
    val state: StateFlow<LoadState<ArtistContent>> = mutableState.asStateFlow()

    private var loading: Job? = null

    init {
        load()
    }

    fun load() {
        if (loading?.isActive == true) return
        mutableState.value = LoadState.Loading
        loading = viewModelScope.launch {
            mutableState.value = loadStateOf(api.artist(id)) { artist ->
                ArtistContent(
                    artist = artist.toTile(api),
                    albums = artist.album
                        .sortedByDescending { it.year ?: Int.MIN_VALUE }
                        .map { it.toTile(api) }
                )
            }
        }
    }

    companion object {
        /** Navigation argument: the artist id. */
        const val ARG_ID = "artistId"
    }
}
