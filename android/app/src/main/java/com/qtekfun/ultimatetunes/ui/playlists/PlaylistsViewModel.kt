// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.playlists

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import com.qtekfun.ultimatetunes.ui.model.LoadError
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.model.PlaylistTile
import com.qtekfun.ultimatetunes.ui.model.loadStateOf
import com.qtekfun.ultimatetunes.ui.model.toLoadError
import com.qtekfun.ultimatetunes.ui.model.toTile
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** What Library › Playlists shows. */
data class PlaylistsUiState(
    val playlists: LoadState<List<PlaylistTile>> = LoadState.Loading,
    val creating: Boolean = false,
    /** A create that failed, shown once. */
    val message: LoadError? = null,
    /** A playlist just created: the screen opens it, then [PlaylistsViewModel.onCreatedOpened]. */
    val created: PlaylistId? = null
)

/** Library › Playlists (RF-09): the user's playlists (`getPlaylists`) and "New Playlist". */
@HiltViewModel
class PlaylistsViewModel @Inject constructor(private val api: TunesApi) : ViewModel() {
    private val mutableState = MutableStateFlow(PlaylistsUiState())
    val state: StateFlow<PlaylistsUiState> = mutableState.asStateFlow()

    private var loading: Job? = null

    /** Loads the list; called each time the screen shows, so renames and deletes appear. */
    fun load() {
        if (loading?.isActive == true) return
        if (mutableState.value.playlists !is LoadState.Ready) {
            mutableState.update { it.copy(playlists = LoadState.Loading) }
        }
        loading = viewModelScope.launch {
            val playlists = loadStateOf(api.playlists()) { list -> list.map { it.toTile(api) } }
            mutableState.update { it.copy(playlists = playlists) }
        }
    }

    /** Creates an empty playlist called [name] (trimmed; blank names are ignored). */
    fun create(name: String) {
        val trimmed = name.trim()
        if (trimmed.isEmpty() || mutableState.value.creating) return
        mutableState.update { it.copy(creating = true) }
        viewModelScope.launch {
            when (val result = api.createPlaylist(trimmed)) {
                is TunesResult.Success -> mutableState.update { state ->
                    val tile = result.value.toTile(api)
                    val list = (state.playlists as? LoadState.Ready)?.value.orEmpty()
                    state.copy(
                        playlists = LoadState.Ready(list + tile),
                        creating = false,
                        created = tile.id
                    )
                }

                is TunesResult.Failure -> mutableState.update {
                    it.copy(creating = false, message = result.toLoadError())
                }
            }
        }
    }

    fun onCreatedOpened() {
        mutableState.update { it.copy(created = null) }
    }

    fun dismissMessage() {
        mutableState.update { it.copy(message = null) }
    }
}
