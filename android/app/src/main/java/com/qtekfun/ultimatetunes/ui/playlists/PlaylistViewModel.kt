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
import com.qtekfun.ultimatetunes.core.library.OfflineChanges
import com.qtekfun.ultimatetunes.core.library.isLocal
import com.qtekfun.ultimatetunes.core.player.offline.CollectionKind
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
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.map
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
 * A playlist and its changes: rename, remove a song and delete. Each shows at once and goes to the
 * offline queue, so it works with no connection. It shows from the local catalog until the server
 * (`getPlaylist`) answers, and again while it has changes waiting, which the server does not have
 * yet; a read that fails keeps what shows. It can be kept offline (RF-12): its songs download and
 * follow its changes.
 */
// Collaborators are injected one by one; one function per change of a playlist.
@Suppress("LongParameterList", "TooManyFunctions")
@HiltViewModel
class PlaylistViewModel @Inject constructor(
    savedStateHandle: SavedStateHandle,
    private val api: TunesApi,
    private val offline: OfflineControls,
    private val changes: OfflineChanges,
    private val repository: LibraryRepository,
    sync: CatalogSync
) : ViewModel() {
    /** The id the screen was opened with: temporary for a playlist made on the phone. */
    private var id = PlaylistId(checkNotNull(savedStateHandle.get<String>(ARG_ID)))

    private val mutableState = MutableStateFlow(PlaylistUiState())
    val state: StateFlow<PlaylistUiState> = mutableState.asStateFlow()

    private var loading: Job? = null

    /** The playlist shown, as changes are made on it. */
    private var shown: Playlist? = null

    /** Changes of this playlist wait to be sent: the catalog knows it better than the server. */
    private var waiting = false

    /** The server's copy shows: the catalog, which may be older, no longer replaces it. */
    private var answered = false

    /** Counts the changes made here: an answer asked before the last one is out of date. */
    private var made = 0

    /** Changes shown and not stored yet: the catalog does not have them all. */
    private var storing = 0

    /** One change at a time, stored in the order made. */
    private val writes = Mutex()

    val refresher = Refresher(viewModelScope) {
        sync.sync()
        reload()
    }

    init {
        viewModelScope.launch { follow() }
        viewModelScope.launch { followKept() }
        load()
    }

    /** The catalog's copy, under the server's id once a playlist made here has one. */
    @OptIn(ExperimentalCoroutinesApi::class)
    private suspend fun follow() {
        changes.replaced.map { it[id] ?: id }
            .distinctUntilChanged()
            .flatMapLatest { now ->
                // Only says that something changed: each one may be older than the others.
                combine(
                    repository.playlist(now),
                    changes.status.map { now in it.playlists }.distinctUntilChanged()
                ) { _, _ -> now }
            }
            .collect(::catchUp)
    }

    /** Reads what the catalog holds now for [now] and shows it, if it is the one to show. */
    private suspend fun catchUp(now: PlaylistId) {
        val renamed = now != id
        id = now
        val asked = made
        val pending = now in changes.status.first().playlists
        val stored = repository.playlist(now).first()
        val sent = waiting && !pending
        waiting = pending
        if (waiting) answered = false
        val outdated = asked != made || storing > 0
        if (!answered && !outdated) stored?.let(::show)
        if (renamed || sent) refresh()
    }

    /** Whether the playlist is kept offline. */
    @OptIn(ExperimentalCoroutinesApi::class)
    private suspend fun followKept() {
        changes.replaced.map { it[id] ?: id }
            .distinctUntilChanged()
            .flatMapLatest { now ->
                offline.selection.map { it.keepsCollection(CollectionKind.PLAYLIST, now.value) }
            }
            .collect { kept -> mutableState.update { it.copy(isOffline = kept) } }
    }

    /** Keeps the playlist on the phone, or stops keeping it. */
    fun toggleOffline() {
        val playlist = (mutableState.value.content as? LoadState.Ready)?.value ?: return
        // The server does not have it yet: there is nothing to keep in step with.
        if (id.isLocal) return
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
        // A playlist the server does not know yet shows from the catalog.
        if (id.isLocal) return
        loading = viewModelScope.launch {
            val error = read()
            mutableState.update {
                if (error == null || it.content is LoadState.Ready) {
                    it
                } else {
                    it.copy(content = LoadState.Failed(error))
                }
            }
        }
    }

    /** Reads the playlist again without hiding what is shown; the screen came back. */
    fun refresh() {
        if (mutableState.value.content !is LoadState.Ready) {
            load()
            return
        }
        viewModelScope.launch { reload() }
    }

    private suspend fun reload(): LoadError? {
        loading?.join()
        return if (id.isLocal) null else read()
    }

    /** Asks the server, showing its answer unless changes wait; why it failed, or null. */
    private suspend fun read(): LoadError? {
        val asked = made
        return when (val result = api.playlist(id)) {
            is TunesResult.Success -> {
                val queued = id in changes.status.first().playlists
                // A change made meanwhile is newer than this answer.
                val outdated = asked != made || storing > 0
                if (!outdated && !waiting && !queued) {
                    answered = true
                    show(result.value)
                }
                null
            }

            is TunesResult.Failure -> result.toLoadError()
        }
    }

    private fun show(playlist: Playlist) {
        shown = playlist
        mutableState.update { it.copy(content = LoadState.Ready(playlist.toContent(api))) }
    }

    fun rename(name: String) {
        val trimmed = name.trim()
        val before = editable() ?: return
        if (trimmed.isEmpty() || trimmed == before.name) return
        change(before.copy(name = trimmed)) { changes.renamePlaylist(before, trimmed) }
    }

    /** Removes the song at [index] of the playlist. */
    fun removeAt(index: Int) {
        val before = editable() ?: return
        if (index !in before.entry.indices) return
        val removed = before.entry[index]
        val after = before.copy(
            entry = before.entry.filterIndexed { i, _ -> i != index },
            songCount = (before.songCount - 1).coerceAtLeast(0),
            duration = (before.duration - (removed.duration ?: 0)).coerceAtLeast(0)
        )
        change(after) { changes.removeFromPlaylist(before, index) }
    }

    fun delete() {
        val playlist = editable() ?: return
        viewModelScope.launch {
            val stored = writes.withLock { changes.deletePlaylist(playlist) }
            if (stored) {
                // Stop keeping it, which frees its downloads.
                if (mutableState.value.isOffline) {
                    offline.dropCollection(CollectionKind.PLAYLIST, id.value)
                }
                mutableState.update { it.copy(deleted = true) }
            } else {
                mutableState.update { it.copy(message = LoadError.STORAGE) }
            }
        }
    }

    fun dismissMessage() {
        mutableState.update { it.copy(message = null) }
    }

    private fun editable(): Playlist? = shown?.takeUnless { it.readonly == true }

    /** Shows [after] at once and stores the change; puts [before] back if that fails. */
    private fun change(after: Playlist, store: suspend () -> Boolean) {
        val before = shown ?: return
        answered = false
        show(after)
        made++
        storing++
        viewModelScope.launch {
            val stored = writes.withLock { store() }
            storing--
            if (!stored) {
                show(before)
                mutableState.update { it.copy(message = LoadError.STORAGE) }
            }
        }
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
