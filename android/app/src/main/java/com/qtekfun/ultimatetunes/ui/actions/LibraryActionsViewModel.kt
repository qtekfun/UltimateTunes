// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.actions

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.library.LibraryRepository
import com.qtekfun.ultimatetunes.core.player.export.ExportStatus
import com.qtekfun.ultimatetunes.core.player.offline.CollectionKind
import com.qtekfun.ultimatetunes.core.player.offline.OfflineState
import com.qtekfun.ultimatetunes.library.CatalogRefresh
import com.qtekfun.ultimatetunes.playback.OfflineControls
import com.qtekfun.ultimatetunes.playback.toPlayable
import com.qtekfun.ultimatetunes.ui.model.LoadError
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.model.PlaylistTile
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import com.qtekfun.ultimatetunes.ui.model.contentState
import com.qtekfun.ultimatetunes.ui.model.toLoadError
import com.qtekfun.ultimatetunes.ui.model.toTile
import com.qtekfun.ultimatetunes.ui.playlists.PlaylistChanges
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

    /** The server downloads at most [max] new songs per change: pick fewer. */
    data class TooManyNew(val max: Int) : ActionEvent

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

/** The server's cap of songs not in the library yet per request. */
private const val MAX_NEW_SONGS = 50

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
    private val exports: Exports,
    private val changes: PlaylistChanges,
    private val repository: LibraryRepository,
    private val catalog: CatalogRefresh
) : ViewModel() {
    private val mutableState = MutableStateFlow(LibraryActionsState())
    val state: StateFlow<LibraryActionsState> = mutableState.asStateFlow()

    /** The favourites the catalog has. */
    private var stored = emptySet<SongId>()

    /** Stars and unstars made here that the catalog does not show yet. */
    private val changed = mutableMapOf<SongId, Boolean>()

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
    }

    /** Says that a song went into the queue. */
    fun queued(next: Boolean) = event(ActionEvent.Queued(next))

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
            } else {
                catalog.request()
                event(ActionEvent.FavouriteChanged(added = favourite))
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
        if (tooManyNew(tracks)) return
        viewModelScope.launch {
            when (
                val result = api.updatePlaylist(
                    playlist.id,
                    songIdsToAdd = tracks.map {
                        it.id
                    }
                )
            ) {
                is TunesResult.Success -> {
                    catalog.request()
                    event(ActionEvent.AddedToPlaylist(playlist.name, tracks.size))
                    changes.changed(playlist.id)
                    val kept = offline.selection.first()
                        .keepsCollection(CollectionKind.PLAYLIST, playlist.id.value)
                    if (kept) offline.syncSoon()
                }

                is TunesResult.Failure -> {
                    // A long list goes in parts: some may have arrived.
                    changes.changed(playlist.id)
                    catalog.request()
                    fail(result)
                }
            }
        }
    }

    /** Creates a playlist called [name] with the picked songs. */
    fun createPlaylist(name: String) {
        val trimmed = name.trim()
        val tracks = mutableState.value.picker?.tracks ?: return
        if (trimmed.isEmpty()) return
        dismissPicker()
        if (!tooManyNew(tracks)) create(trimmed, tracks)
    }

    private fun create(name: String, tracks: List<TrackTile>) {
        viewModelScope.launch {
            when (val result = api.createPlaylist(name, tracks.map { it.id })) {
                is TunesResult.Success -> {
                    catalog.request()
                    event(ActionEvent.AddedToPlaylist(name, tracks.size))
                }

                is TunesResult.Failure -> fail(result)
            }
        }
    }

    private fun tooManyNew(tracks: List<TrackTile>): Boolean {
        val tooMany = tracks.count { it.isExternal } > MAX_NEW_SONGS
        if (tooMany) event(ActionEvent.TooManyNew(MAX_NEW_SONGS))
        return tooMany
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
        changed[id] = favourite
        publishFavourites()
    }

    private fun publishFavourites() {
        val added = changed.filterValues { it }.keys
        val removed = changed.filterValues { !it }.keys
        mutableState.update { it.copy(favourites = stored + added - removed) }
    }

    private fun fail(failure: TunesResult.Failure) =
        event(ActionEvent.Failed(failure.toLoadError()))

    private fun event(event: ActionEvent) {
        mutableState.update { it.copy(event = event) }
    }
}
