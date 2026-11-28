// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.library

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.availability.Availability
import com.qtekfun.ultimatetunes.availability.PhoneAvailability
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.model.ArtistId
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import com.qtekfun.ultimatetunes.core.library.CatalogSync
import com.qtekfun.ultimatetunes.core.library.LibraryRepository
import com.qtekfun.ultimatetunes.core.library.OfflineChanges
import com.qtekfun.ultimatetunes.core.player.offline.CollectionKind
import com.qtekfun.ultimatetunes.playback.OfflineControls
import com.qtekfun.ultimatetunes.ui.model.AlbumTile
import com.qtekfun.ultimatetunes.ui.model.ArtistTile
import com.qtekfun.ultimatetunes.ui.model.LoadError
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.model.PlaylistTile
import com.qtekfun.ultimatetunes.ui.model.Refresher
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import com.qtekfun.ultimatetunes.ui.model.contentState
import com.qtekfun.ultimatetunes.ui.model.syncError
import com.qtekfun.ultimatetunes.ui.model.toLoadError
import com.qtekfun.ultimatetunes.ui.model.toTile
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** What the Library shows; podcasts will be one more (PLAN Wave 5). */
enum class LibraryFilter { PLAYLISTS, ALBUMS, ARTISTS, SONGS }

/** The list of one [LibraryFilter]. */
sealed interface LibraryItems {
    val filter: LibraryFilter
    val isEmpty: Boolean

    data class Playlists(val playlists: List<PlaylistTile>) : LibraryItems {
        override val filter get() = LibraryFilter.PLAYLISTS
        override val isEmpty get() = playlists.isEmpty()
    }

    data class Albums(val albums: List<AlbumTile>) : LibraryItems {
        override val filter get() = LibraryFilter.ALBUMS
        override val isEmpty get() = albums.isEmpty()
    }

    data class Artists(val artists: List<ArtistTile>) : LibraryItems {
        override val filter get() = LibraryFilter.ARTISTS
        override val isEmpty get() = artists.isEmpty()
    }

    data class Songs(val songs: List<TrackTile>) : LibraryItems {
        override val filter get() = LibraryFilter.SONGS
        override val isEmpty get() = songs.isEmpty()
    }
}

/** "New playlist" under way and how it ended. */
data class NewPlaylist(
    val creating: Boolean = false,
    /** A create that failed, shown once. */
    val message: LoadError? = null,
    /** A playlist just created: the screen opens it, then [LibraryViewModel.onCreatedOpened]. */
    val created: PlaylistId? = null
)

/** What the Library tab shows. */
data class LibraryUiState(
    val filter: LibraryFilter = LibraryFilter.PLAYLISTS,
    /** The "On this phone" chip; offline mode forces it on. */
    val onPhoneOnly: Boolean = false,
    val offlineMode: Boolean = false,
    val items: LoadState<LibraryItems> = LoadState.Loading,
    val favouriteCount: Int = 0,
    val downloadCount: Int = 0,
    /** The playlists kept on the phone, for their menus. */
    val keptPlaylists: Set<PlaylistId> = emptySet(),
    val newPlaylist: NewPlaylist = NewPlaylist(),
    val syncError: LoadError? = null
)

/**
 * The Library tab (RF-11): playlists, albums, artists or songs straight from the local catalog,
 * all of it or only what is on the phone, and "New playlist".
 */
// Collaborators are injected one by one; one function per action of the screen.
@Suppress("LongParameterList", "TooManyFunctions")
@HiltViewModel
class LibraryViewModel @Inject constructor(
    private val savedState: SavedStateHandle,
    private val api: TunesApi,
    private val repository: LibraryRepository,
    private val sync: CatalogSync,
    private val changes: OfflineChanges,
    private val phone: PhoneAvailability,
    downloads: OfflineLibrary,
    private val offline: OfflineControls
) : ViewModel() {
    private val newPlaylist = MutableStateFlow(NewPlaylist())

    val refresher = Refresher(viewModelScope) { sync.syncError() }

    private val filter: Flow<LibraryFilter> =
        savedState.getStateFlow(KEY_FILTER, LibraryFilter.PLAYLISTS.name)
            .map(LibraryFilter::valueOf)

    private val onPhoneOnly = savedState.getStateFlow(KEY_ON_PHONE, false)

    /** What to keep the lists to; null to show everything. */
    private val keptTo: Flow<Availability?> =
        combine(onPhoneOnly, phone.availability) { toggle, now ->
            now.takeIf { toggle || it.offlineMode }
        }.distinctUntilChanged()

    @OptIn(ExperimentalCoroutinesApi::class)
    private val items: Flow<LibraryItems> =
        filter.flatMapLatest(::itemsOf).flowOn(Dispatchers.Default)

    private val choices = combine(filter, onPhoneOnly, phone.availability, newPlaylist, ::Choices)

    private val extras = combine(
        repository.favouriteSongs().map { it.size },
        downloads.downloads.map { it.size },
        offline.selection.map { selection ->
            selection.collections.filter { it.kind == CollectionKind.PLAYLIST }
                .mapTo(HashSet()) { PlaylistId(it.id) }
        },
        ::Triple
    )

    val state: StateFlow<LibraryUiState> =
        combine(choices, items, extras, repository.syncState) { chosen, list, counts, synced ->
            LibraryUiState(
                filter = chosen.filter,
                onPhoneOnly = chosen.onPhoneOnly || chosen.availability.offlineMode,
                offlineMode = chosen.availability.offlineMode,
                // The list of the filter chosen before is not shown under the new one.
                items = if (list.filter == chosen.filter) {
                    synced.contentState { list }
                } else {
                    LoadState.Loading
                },
                favouriteCount = counts.first,
                downloadCount = counts.second,
                keptPlaylists = counts.third,
                newPlaylist = chosen.newPlaylist,
                syncError = synced.error?.toLoadError()
            )
        }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(STOP_TIMEOUT_MS), LibraryUiState())

    fun select(filter: LibraryFilter) {
        savedState[KEY_FILTER] = filter.name
    }

    fun setOnPhoneOnly(value: Boolean) {
        savedState[KEY_ON_PHONE] = value
    }

    /** The songs of the playlist [id], for its menu. */
    suspend fun playlistTracks(id: PlaylistId): List<TrackTile> =
        repository.playlist(id).first()?.entry.orEmpty().map { it.toTile(api) }

    /** The library songs of the artist [id], for their menu. */
    suspend fun artistTracks(id: ArtistId): List<TrackTile> =
        repository.artistSongs(id).first().map { it.toTile(api) }

    /** Keeps the playlist on the phone, or stops keeping it. */
    fun toggleOffline(playlist: PlaylistTile) {
        viewModelScope.launch {
            if (offline.selection.first()
                    .keepsCollection(CollectionKind.PLAYLIST, playlist.id.value)
            ) {
                offline.dropCollection(CollectionKind.PLAYLIST, playlist.id.value)
            } else {
                offline.keepCollection(CollectionKind.PLAYLIST, playlist.id.value, playlist.name)
            }
        }
    }

    /** Creates an empty playlist called [name] (trimmed; blank names are ignored). */
    fun create(name: String) {
        val trimmed = name.trim()
        if (trimmed.isEmpty() || newPlaylist.value.creating) return
        newPlaylist.update { it.copy(creating = true) }
        viewModelScope.launch {
            val id = changes.createPlaylist(trimmed)
            newPlaylist.value = NewPlaylist(
                created = id,
                message = LoadError.STORAGE.takeIf { id == null }
            )
        }
    }

    fun onCreatedOpened() {
        newPlaylist.update { it.copy(created = null) }
    }

    fun dismissMessage() {
        newPlaylist.update { it.copy(message = null) }
    }

    private fun itemsOf(filter: LibraryFilter): Flow<LibraryItems> = when (filter) {
        LibraryFilter.PLAYLISTS -> combine(repository.playlists(), keptTo) { all, only ->
            val shown = all.filter { only == null || it.id in only.playlists }
            LibraryItems.Playlists(shown.map { it.toTile(api) })
        }

        LibraryFilter.ALBUMS -> combine(repository.albums(), keptTo) { all, only ->
            val shown = all.filter { only == null || it.id in only.albums }
            LibraryItems.Albums(shown.map { it.toTile(api) })
        }

        LibraryFilter.ARTISTS -> combine(repository.artists(), keptTo) { all, only ->
            val shown = all.filter { only == null || it.id in only.artists }
            LibraryItems.Artists(shown.map { it.toTile(api) })
        }

        LibraryFilter.SONGS -> combine(repository.songs(), keptTo) { all, only ->
            val shown = all.filter { only == null || only.phoneId(it.id) != null }
            LibraryItems.Songs(shown.map { it.toTile(api) })
        }
    }

    private data class Choices(
        val filter: LibraryFilter,
        val onPhoneOnly: Boolean,
        val availability: Availability,
        val newPlaylist: NewPlaylist
    )

    private companion object {
        const val KEY_FILTER = "filter"
        const val KEY_ON_PHONE = "onPhone"
        const val STOP_TIMEOUT_MS = 5_000L
    }
}

/** How many songs of the whole list a tap queues before and from the song tapped. */
private const val QUEUE_BEFORE = 50
private const val QUEUE_FROM = 450

/**
 * The queue a tap on [tracks] at [index] starts, and the place of the song in it: a stretch of
 * the list around it, as a library of tens of thousands of songs is too long for one queue.
 */
internal fun queueWindow(tracks: List<TrackTile>, index: Int): Pair<List<TrackTile>, Int> {
    val from = (index - QUEUE_BEFORE).coerceAtLeast(0)
    val to = (index + QUEUE_FROM).coerceAtMost(tracks.size)
    return tracks.subList(from, to).toList() to index - from
}
