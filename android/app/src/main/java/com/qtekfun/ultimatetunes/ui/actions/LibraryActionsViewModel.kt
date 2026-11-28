// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.actions

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.model.Playlist
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.library.ChangeNotice
import com.qtekfun.ultimatetunes.core.library.LibraryRepository
import com.qtekfun.ultimatetunes.core.library.OfflineChanges
import com.qtekfun.ultimatetunes.core.player.export.ExportStatus
import com.qtekfun.ultimatetunes.core.player.offline.CollectionKind
import com.qtekfun.ultimatetunes.core.player.offline.OfflineState
import com.qtekfun.ultimatetunes.playback.OfflineControls
import com.qtekfun.ultimatetunes.playback.toPlayable
import com.qtekfun.ultimatetunes.ui.model.LoadError
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.model.PlaylistTile
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import com.qtekfun.ultimatetunes.ui.model.contentState
import com.qtekfun.ultimatetunes.ui.model.toSong
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

    /** A change made earlier could not be sent and was dropped. */
    data class ChangeDropped(val notice: ChangeNotice) : ActionEvent

    /** A song went into the queue: right after the current one ([next]) or at the end. */
    data class Queued(val next: Boolean) : ActionEvent

    data object DownloadRemoved : ActionEvent

    /** A song was starred ([added]) or unstarred. */
    data class FavouriteChanged(val added: Boolean) : ActionEvent

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
    /** Songs on the phone because of a kept album, playlist or the whole library. */
    val keptByGroup: Set<SongId> = emptySet(),
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
 * playlist menus; SPEC §5): favourite, add to a playlist (or a new one), keep offline (RF-12) and
 * export to the phone (RF-14). Favourites and playlists go through the offline queue, so they work
 * with no connection; what the server later refuses is said here. Lives as long as the activity.
 */

@Suppress("TooManyFunctions") // One function per menu action.
@HiltViewModel
class LibraryActionsViewModel @Inject constructor(
    private val api: TunesApi,
    private val offline: OfflineControls,
    private val exports: Exports,
    private val changes: OfflineChanges,
    private val repository: LibraryRepository
) : ViewModel() {
    private val mutableState = MutableStateFlow(LibraryActionsState())
    val state: StateFlow<LibraryActionsState> = mutableState.asStateFlow()

    /** The favourites the catalog has. */
    private var stored = emptySet<SongId>()

    /** Stars and unstars made here that the catalog does not show yet. */
    private val changed = mutableMapOf<SongId, Boolean>()

    /** The oldest change the user has not been told was dropped. */
    private var notice: ChangeNotice? = null

    /** Songs waiting for the export folder. */
    private var pendingExport: List<TrackTile> = emptyList()

    init {
        viewModelScope.launch {
            offline.selection.collect { selection ->
                mutableState.update { state ->
                    val grouped = selection.collections.flatMap { it.members.orEmpty() } +
                        selection.library?.songs.orEmpty()
                    val ids = grouped.mapTo(HashSet()) { it.id }
                    // A `yt:` song downloaded under its library id counts under both.
                    ids += selection.aliases.filterValues { it in ids }.keys
                    state.copy(
                        keptOffline = selection.tracks.mapTo(HashSet()) { it.id },
                        keptByGroup = ids
                    )
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
        viewModelScope.launch {
            repository.favouriteSongs().collect { songs ->
                stored = songs.mapTo(HashSet()) { it.id }
                changed.entries.removeAll { (id, favourite) -> (id in stored) == favourite }
                publishFavourites()
            }
        }
        viewModelScope.launch {
            changes.notices.collect { notices ->
                val first = notices.firstOrNull()
                val new = first != notice
                notice = first
                if (new && first != null) event(ActionEvent.ChangeDropped(first))
            }
        }
    }

    /** Says that a song went into the queue. */
    fun queued(next: Boolean) = event(ActionEvent.Queued(next))

    /** Stars or unstars [track], showing the change at once. */
    fun toggleFavourite(track: TrackTile) {
        val favourite = track.id !in mutableState.value.favourites
        setFavourite(track.id, favourite)
        viewModelScope.launch {
            if (changes.setSongFavourite(track.toSong(), favourite)) {
                event(ActionEvent.FavouriteChanged(added = favourite))
            } else {
                setFavourite(track.id, !favourite)
                event(ActionEvent.Failed(LoadError.STORAGE))
            }
        }
    }

    /** Opens "Add to Playlist" for [tracks] and loads the playlists. */
    fun pickPlaylist(tracks: List<TrackTile>) {
        if (tracks.isEmpty()) return
        mutableState.update { it.copy(picker = PlaylistPicker(tracks)) }
        viewModelScope.launch {
            val all = repository.playlists().first()
            val playlists = repository.syncState.first().contentState {
                all.filter { it.readonly != true }.map { it.toTile(api) }
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
            val held = repository.playlist(playlist.id).first()
                ?: Playlist(playlist.id, playlist.name)
            added(changes.addToPlaylist(held, tracks.map { it.toSong() }), playlist.name, tracks)
        }
    }

    /** Creates a playlist called [name] with the picked songs. */
    fun createPlaylist(name: String) {
        val trimmed = name.trim()
        val tracks = mutableState.value.picker?.tracks ?: return
        if (trimmed.isEmpty()) return
        dismissPicker()
        viewModelScope.launch {
            val created = changes.createPlaylist(trimmed, tracks.map { it.toSong() })
            added(created != null, trimmed, tracks)
        }
    }

    private fun added(stored: Boolean, playlist: String, tracks: List<TrackTile>) = event(
        if (stored) {
            ActionEvent.AddedToPlaylist(playlist, tracks.size)
        } else {
            ActionEvent.Failed(LoadError.STORAGE)
        }
    )

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
        val shown = mutableState.value.event
        mutableState.update { it.copy(event = null) }
        if (shown is ActionEvent.ChangeDropped) {
            viewModelScope.launch { changes.dismiss(shown.notice.id) }
        } else {
            // Another message may have taken a notice's place before it was seen: show it again.
            notice?.let { event(ActionEvent.ChangeDropped(it)) }
        }
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
        changed[id] = favourite
        publishFavourites()
    }

    private fun publishFavourites() {
        val added = changed.filterValues { it }.keys
        val removed = changed.filterValues { !it }.keys
        mutableState.update { it.copy(favourites = stored + added - removed) }
    }

    private fun event(event: ActionEvent) {
        mutableState.update { it.copy(event = event) }
    }
}
