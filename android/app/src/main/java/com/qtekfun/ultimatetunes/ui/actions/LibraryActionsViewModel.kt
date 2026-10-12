// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.actions

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.player.export.ExportStatus
import com.qtekfun.ultimatetunes.core.player.offline.OfflineState
import com.qtekfun.ultimatetunes.playback.OfflineControls
import com.qtekfun.ultimatetunes.playback.toPlayable
import com.qtekfun.ultimatetunes.ui.model.LoadError
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.model.PlaylistTile
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import com.qtekfun.ultimatetunes.ui.model.loadStateOf
import com.qtekfun.ultimatetunes.ui.model.toLoadError
import com.qtekfun.ultimatetunes.ui.model.toTile
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** "Add to Playlist" open for [tracks]: the user's playlists to choose from. */
data class PlaylistPicker(
    val tracks: List<TrackTile>,
    val playlists: LoadState<List<PlaylistTile>> = LoadState.Loading
)

/** What happened after an action, shown once. */
sealed interface ActionEvent {
    data class AddedToPlaylist(val playlist: String, val count: Int) : ActionEvent

    data object Downloading : ActionEvent

    data object DownloadRemoved : ActionEvent

    data class ExportStarted(val count: Int) : ActionEvent

    /** Another export is still running; this one did not start. */
    data object ExportBusy : ActionEvent

    data class Failed(val error: LoadError) : ActionEvent
}

/** What the song menus, "Add to Playlist" and the export show. */
data class LibraryActionsState(
    /** Starred songs (RF-09). */
    val favourites: Set<SongId> = emptySet(),
    /** Songs kept offline on their own (RF-12). */
    val keptOffline: Set<SongId> = emptySet(),
    /** Songs fully downloaded. */
    val downloaded: Set<SongId> = emptySet(),
    val picker: PlaylistPicker? = null,
    /** An export waits for the user to pick a folder (the screen opens the system picker). */
    val needsFolder: Boolean = false,
    val export: ExportStatus = ExportStatus.Idle,
    val event: ActionEvent? = null
)

/**
 * The actions on songs offered everywhere (long-press menus, the full player's menu, album and
 * playlist menus; SPEC §5): favourite (`star`/`unstar`), add to a playlist (`updatePlaylist`, or a
 * new one with `createPlaylist`), keep offline (RF-12) and export to the phone (RF-14). Lives as
 * long as the activity.
 */
@Suppress("TooManyFunctions") // One function per menu action.
@HiltViewModel
class LibraryActionsViewModel @Inject constructor(
    private val api: TunesApi,
    private val offline: OfflineControls,
    private val exports: Exports
) : ViewModel() {
    private val mutableState = MutableStateFlow(LibraryActionsState())
    val state: StateFlow<LibraryActionsState> = mutableState.asStateFlow()

    /** Songs waiting for the export folder. */
    private var pendingExport: List<TrackTile> = emptyList()

    init {
        viewModelScope.launch {
            offline.selection.collect { selection ->
                mutableState.update { state ->
                    state.copy(keptOffline = selection.tracks.mapTo(HashSet()) { it.id })
                }
            }
        }
        viewModelScope.launch {
            offline.items.collect { items ->
                mutableState.update { state ->
                    state.copy(
                        downloaded = items.filter { it.state == OfflineState.DONE }
                            .mapTo(HashSet()) { it.track.id }
                    )
                }
            }
        }
        viewModelScope.launch {
            exports.status.collect { status -> mutableState.update { it.copy(export = status) } }
        }
        refreshFavourites()
    }

    /** Reads the favourites again (a menu is about to show them). */
    fun refreshFavourites() {
        viewModelScope.launch {
            val starred = api.starred()
            if (starred is TunesResult.Success) {
                mutableState.update { state ->
                    state.copy(favourites = starred.value.song.mapTo(HashSet()) { it.id })
                }
            }
        }
    }

    /** Stars or unstars [track], showing the change at once and undoing it if it fails. */
    fun toggleFavourite(track: TrackTile) {
        val favourite = track.id !in mutableState.value.favourites
        setFavourite(track.id, favourite)
        viewModelScope.launch {
            val ids = listOf(track.id)
            val result = if (favourite) api.star(songIds = ids) else api.unstar(songIds = ids)
            if (result is TunesResult.Failure) {
                setFavourite(track.id, !favourite)
                fail(result)
            }
        }
    }

    /** Opens "Add to Playlist" for [tracks] and loads the playlists. */
    fun pickPlaylist(tracks: List<TrackTile>) {
        if (tracks.isEmpty()) return
        mutableState.update { it.copy(picker = PlaylistPicker(tracks)) }
        viewModelScope.launch {
            val playlists = loadStateOf(api.playlists()) { list ->
                list.filter { it.readonly != true }.map { it.toTile(api) }
            }
            mutableState.update { state ->
                state.copy(picker = state.picker?.copy(playlists = playlists))
            }
        }
    }

    fun dismissPicker() {
        mutableState.update { it.copy(picker = null) }
    }

    /** Adds the picked songs at the end of [playlist]. */
    fun addToPlaylist(playlist: PlaylistTile) {
        val tracks = mutableState.value.picker?.tracks ?: return
        dismissPicker()
        viewModelScope.launch {
            when (
                val result = api.updatePlaylist(
                    playlist.id,
                    songIdsToAdd = tracks.map {
                        it.id
                    }
                )
            ) {
                is TunesResult.Success -> event(
                    ActionEvent.AddedToPlaylist(playlist.name, tracks.size)
                )

                is TunesResult.Failure -> fail(result)
            }
        }
    }

    /** Creates a playlist called [name] with the picked songs. */
    fun createPlaylist(name: String) {
        val trimmed = name.trim()
        val tracks = mutableState.value.picker?.tracks ?: return
        if (trimmed.isEmpty()) return
        dismissPicker()
        viewModelScope.launch {
            when (val result = api.createPlaylist(trimmed, tracks.map { it.id })) {
                is TunesResult.Success -> event(ActionEvent.AddedToPlaylist(trimmed, tracks.size))
                is TunesResult.Failure -> fail(result)
            }
        }
    }

    /** Keeps [track] on the phone (RF-12), or stops keeping it. */
    fun toggleDownload(track: TrackTile) {
        val kept = track.id in mutableState.value.keptOffline
        viewModelScope.launch {
            if (kept) {
                offline.dropTrack(track.id)
                event(ActionEvent.DownloadRemoved)
            } else {
                offline.keepTrack(track.toPlayable())
                event(ActionEvent.Downloading)
            }
        }
    }

    /**
     * Exports [tracks] to the phone (RF-14) into the folder picked before, or asks for one first
     * ([LibraryActionsState.needsFolder]).
     */
    fun export(tracks: List<TrackTile>) {
        if (tracks.isEmpty()) return
        viewModelScope.launch {
            val folder = exports.folder.first()
            if (folder == null) {
                pendingExport = tracks
                mutableState.update { it.copy(needsFolder = true) }
            } else {
                startExport(folder, tracks)
            }
        }
    }

    /** The system folder picker closed: [uri] is the folder, or null when cancelled. */
    fun onFolderPicked(uri: String?) {
        val tracks = pendingExport
        pendingExport = emptyList()
        mutableState.update { it.copy(needsFolder = false) }
        if (uri == null) return
        viewModelScope.launch {
            exports.setFolder(uri)
            val folder = exports.folder.first()
            if (folder != null && tracks.isNotEmpty()) startExport(folder, tracks)
        }
    }

    /** The export report was seen. */
    fun dismissExport() = exports.dismiss()

    fun dismissEvent() {
        mutableState.update { it.copy(event = null) }
    }

    private suspend fun startExport(folder: String, tracks: List<TrackTile>) {
        val aliases = offline.selection.first().aliases
        val started = exports.start(folder, tracks.map { it.toPlayable() }, aliases)
        event(
            if (started) {
                ActionEvent.ExportStarted(tracks.distinctBy { it.id }.size)
            } else {
                ActionEvent.ExportBusy
            }
        )
    }

    private fun setFavourite(id: SongId, favourite: Boolean) {
        mutableState.update { state ->
            state.copy(
                favourites = if (favourite) state.favourites + id else state.favourites - id
            )
        }
    }

    private fun fail(failure: TunesResult.Failure) =
        event(ActionEvent.Failed(failure.toLoadError()))

    private fun event(event: ActionEvent) {
        mutableState.update { it.copy(event = event) }
    }
}
