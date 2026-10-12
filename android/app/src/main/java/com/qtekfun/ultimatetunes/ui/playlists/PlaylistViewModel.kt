// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.playlists

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import com.qtekfun.ultimatetunes.ui.model.LoadError
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.model.PlaylistTile
import com.qtekfun.ultimatetunes.ui.model.TrackTile
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

/** A playlist with its songs. */
data class PlaylistContent(
    val playlist: PlaylistTile,
    val comment: String?,
    val tracks: List<TrackTile>,
    /** Someone else's playlist: it can be played, not changed. */
    val readonly: Boolean
)

/** What the playlist screen shows. */
data class PlaylistUiState(
    val content: LoadState<PlaylistContent> = LoadState.Loading,
    /** A change that failed, shown once. */
    val message: LoadError? = null,
    /** True once the playlist is deleted: the screen goes back. */
    val deleted: Boolean = false
)

/**
 * A playlist (`getPlaylist`) and its changes: rename and remove a song (`updatePlaylist`), delete
 * (`deletePlaylist`). Changes show at once and are undone if the server refuses them.
 */
@HiltViewModel
class PlaylistViewModel @Inject constructor(
    savedStateHandle: SavedStateHandle,
    private val api: TunesApi
) : ViewModel() {
    private val id = PlaylistId(checkNotNull(savedStateHandle.get<String>(ARG_ID)))

    private val mutableState = MutableStateFlow(PlaylistUiState())
    val state: StateFlow<PlaylistUiState> = mutableState.asStateFlow()

    private var loading: Job? = null

    init {
        load()
    }

    fun load() {
        if (loading?.isActive == true) return
        mutableState.update { it.copy(content = LoadState.Loading) }
        loading = viewModelScope.launch {
            val content = loadStateOf(api.playlist(id)) { playlist ->
                PlaylistContent(
                    playlist = playlist.toTile(api),
                    comment = playlist.comment,
                    tracks = playlist.entry.map { it.toTile(api) },
                    readonly = playlist.readonly == true
                )
            }
            mutableState.update { it.copy(content = content) }
        }
    }

    fun rename(name: String) {
        val trimmed = name.trim()
        val before = editable() ?: return
        if (trimmed.isEmpty() || trimmed == before.playlist.name) return
        change(before, before.copy(playlist = before.playlist.copy(name = trimmed))) {
            api.updatePlaylist(id, name = trimmed)
        }
    }

    /** Removes the song at [index] of the playlist. */
    fun removeAt(index: Int) {
        val before = editable() ?: return
        if (index !in before.tracks.indices) return
        val removed = before.tracks[index]
        val after = before.copy(
            tracks = before.tracks.filterIndexed { i, _ -> i != index },
            playlist = before.playlist.copy(
                songCount = (before.playlist.songCount - 1).coerceAtLeast(0),
                durationSec = (before.playlist.durationSec - (removed.durationSec ?: 0))
                    .coerceAtLeast(0)
            )
        )
        change(before, after) { api.updatePlaylist(id, songIndexesToRemove = listOf(index)) }
    }

    fun delete() {
        editable() ?: return
        viewModelScope.launch {
            when (val result = api.deletePlaylist(id)) {
                is TunesResult.Success -> mutableState.update { it.copy(deleted = true) }

                is TunesResult.Failure -> mutableState.update {
                    it.copy(message = result.toLoadError())
                }
            }
        }
    }

    fun dismissMessage() {
        mutableState.update { it.copy(message = null) }
    }

    private fun editable(): PlaylistContent? =
        ((mutableState.value.content as? LoadState.Ready)?.value)?.takeUnless { it.readonly }

    private fun change(
        before: PlaylistContent,
        after: PlaylistContent,
        call: suspend () -> TunesResult<Unit>
    ) {
        mutableState.update { it.copy(content = LoadState.Ready(after)) }
        viewModelScope.launch {
            val result = call()
            if (result is TunesResult.Failure) {
                mutableState.update {
                    it.copy(content = LoadState.Ready(before), message = result.toLoadError())
                }
            }
        }
    }

    companion object {
        /** Navigation argument: the playlist id. */
        const val ARG_ID = "playlistId"
    }
}
