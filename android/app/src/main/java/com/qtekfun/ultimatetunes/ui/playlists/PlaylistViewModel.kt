// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.playlists

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.model.Playlist
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import com.qtekfun.ultimatetunes.core.library.CatalogSync
import com.qtekfun.ultimatetunes.core.library.LibraryRepository
import com.qtekfun.ultimatetunes.core.player.offline.CollectionKind
import com.qtekfun.ultimatetunes.library.CatalogRefresh
import com.qtekfun.ultimatetunes.playback.OfflineControls
import com.qtekfun.ultimatetunes.ui.model.LoadError
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.model.PlaylistTile
import com.qtekfun.ultimatetunes.ui.model.Refresher
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import com.qtekfun.ultimatetunes.ui.model.toLoadError
import com.qtekfun.ultimatetunes.ui.model.toTile
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.filter
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

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
    val deleted: Boolean = false,
    /** Kept on the phone, in sync with the server (RF-12). */
    val isOffline: Boolean = false
)

/**
 * A playlist and its changes: rename and remove a song (`updatePlaylist`), delete
 * (`deletePlaylist`). It shows from the local catalog, with no connection too, until the server
 * (`getPlaylist`) answers; a read that fails keeps what shows.
 * Changes show at once; if the server refuses one, the playlist is read again
 * (another device may have changed it meanwhile, so an old copy could be wrong). It can be kept
 * offline (RF-12): its songs download and follow its changes.
 */
// Collaborators are injected one by one; one function per change of a playlist.
@Suppress("LongParameterList", "TooManyFunctions")
@HiltViewModel
class PlaylistViewModel @Inject constructor(
    savedStateHandle: SavedStateHandle,
    private val api: TunesApi,
    private val offline: OfflineControls,
    changes: PlaylistChanges,
    repository: LibraryRepository,
    sync: CatalogSync,
    private val catalog: CatalogRefresh
) : ViewModel() {
    private val id = PlaylistId(checkNotNull(savedStateHandle.get<String>(ARG_ID)))

    private val mutableState = MutableStateFlow(PlaylistUiState())
    val state: StateFlow<PlaylistUiState> = mutableState.asStateFlow()

    private var loading: Job? = null

    /** One change at a time, so removals by index reach the server in the order made. */
    private val writes = Mutex()

    /** Grows when a change fails: the ones queued behind it were made on a state that is gone. */
    private var generation = 0

    /** Changes shown but not answered yet: the server's list does not have them all. */
    private var pending = 0

    /** An answer was set aside because of [pending] changes: read again after the last one. */
    private var outdated = false

    /** The list shown was not read from the server since: its positions cannot be trusted. */
    private var unverified = false

    /** The server's copy shows: the catalog, which may be older, no longer replaces it. */
    private var answered = false

    val refresher = Refresher(viewModelScope) {
        sync.sync()
        writes.withLock { reload() }
    }

    init {
        viewModelScope.launch {
            repository.playlist(id).collect { playlist ->
                if (!answered && pending == 0 && playlist != null) {
                    unverified = true
                    mutableState.update {
                        it.copy(content = LoadState.Ready(playlist.toContent(api)))
                    }
                }
            }
        }
        viewModelScope.launch { changes.changed.filter { it == id }.collect { refresh() } }
        viewModelScope.launch {
            offline.selection.collect { selection ->
                val kept = selection.keepsCollection(CollectionKind.PLAYLIST, id.value)
                mutableState.update { it.copy(isOffline = kept) }
            }
        }
        load()
    }

    /** Keeps the playlist on the phone, or stops keeping it. */
    fun toggleOffline() {
        val playlist = (mutableState.value.content as? LoadState.Ready)?.value ?: return
        val kept = mutableState.value.isOffline
        viewModelScope.launch {
            if (kept) {
                offline.dropCollection(CollectionKind.PLAYLIST, id.value)
            } else {
                offline.keepCollection(CollectionKind.PLAYLIST, id.value, playlist.playlist.name)
            }
        }
    }

    fun load() {
        if (loading?.isActive == true) return
        mutableState.update {
            it.copy(content = it.content as? LoadState.Ready ?: LoadState.Loading)
        }
        loading = viewModelScope.launch {
            when (val result = api.playlist(id)) {
                is TunesResult.Success -> show(result.value)

                is TunesResult.Failure -> mutableState.update {
                    if (it.content is LoadState.Ready) {
                        it
                    } else {
                        it.copy(content = LoadState.Failed(result.toLoadError()))
                    }
                }
            }
        }
    }

    private fun show(playlist: Playlist) {
        answered = true
        unverified = false
        mutableState.update { it.copy(content = LoadState.Ready(playlist.toContent(api))) }
    }

    /** Reads the playlist again without hiding what is shown; the screen came back. */
    fun refresh() {
        if (mutableState.value.content !is LoadState.Ready) {
            load()
            return
        }
        viewModelScope.launch { writes.withLock { reload() } }
    }

    fun rename(name: String) {
        val trimmed = name.trim()
        val before = editable() ?: return
        if (trimmed.isEmpty() || trimmed == before.playlist.name) return
        change(before.copy(playlist = before.playlist.copy(name = trimmed))) {
            api.updatePlaylist(id, name = trimmed)
        }
    }

    /** Removes the song at [index] of the playlist. */
    fun removeAt(index: Int) {
        val before = editable() ?: return
        // Unverified positions: read the list instead of removing the wrong song.
        if (unverified) readBeforeEditing()
        if (unverified || index !in before.tracks.indices) return
        val removed = before.tracks[index]
        val after = before.copy(
            tracks = before.tracks.filterIndexed { i, _ -> i != index },
            playlist = before.playlist.copy(
                songCount = (before.playlist.songCount - 1).coerceAtLeast(0),
                durationSec = (before.playlist.durationSec - (removed.durationSec ?: 0))
                    .coerceAtLeast(0)
            )
        )
        change(after) { api.updatePlaylist(id, songIndexesToRemove = listOf(index)) }
    }

    /** Reads the list a change by position needs, and says so if it cannot. */
    private fun readBeforeEditing() {
        viewModelScope.launch {
            val error = writes.withLock { reload() }
            if (error != null) mutableState.update { it.copy(message = error) }
        }
    }

    fun delete() {
        editable() ?: return
        viewModelScope.launch {
            when (val result = api.deletePlaylist(id)) {
                is TunesResult.Success -> {
                    // Gone on the server: stop keeping it, which frees its downloads.
                    if (mutableState.value.isOffline) {
                        offline.dropCollection(CollectionKind.PLAYLIST, id.value)
                    }
                    catalog.request()
                    mutableState.update { it.copy(deleted = true) }
                }

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

    /** Shows [after] at once, then [call]s the server; on a failure, puts the old state back. */
    private fun change(after: PlaylistContent, call: suspend () -> TunesResult<Unit>) {
        val before = mutableState.value.content
        val made = generation
        pending++
        mutableState.update { it.copy(content = LoadState.Ready(after)) }
        viewModelScope.launch {
            writes.withLock {
                val result = if (made == generation) call() else null
                pending--
                if (result is TunesResult.Failure) {
                    generation++
                    unverified = true
                    outdated = true
                    mutableState.update {
                        it.copy(content = before, message = result.toLoadError())
                    }
                } else if (result != null) {
                    catalog.request()
                    if (mutableState.value.isOffline) offline.syncSoon()
                }
                if (outdated && pending == 0) reload()
            }
        }
    }

    /** Reads the playlist again, keeping what is shown; why that failed, or null. */
    private suspend fun reload(): LoadError? {
        loading?.join()
        val result = api.playlist(id)
        outdated = pending > 0
        if (result is TunesResult.Success && !outdated) show(result.value)
        return (result as? TunesResult.Failure)?.toLoadError()
    }

    companion object {
        /** Navigation argument: the playlist id. */
        const val ARG_ID = "playlistId"
    }
}

private fun Playlist.toContent(api: TunesApi) = PlaylistContent(
    playlist = toTile(api),
    comment = comment,
    tracks = entry.map { it.toTile(api) },
    readonly = readonly == true
)
