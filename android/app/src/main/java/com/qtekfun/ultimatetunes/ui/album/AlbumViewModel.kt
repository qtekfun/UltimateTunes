// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.album

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.model.Album
import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.ArtistId
import com.qtekfun.ultimatetunes.core.library.CatalogSync
import com.qtekfun.ultimatetunes.core.library.LibraryRepository
import com.qtekfun.ultimatetunes.core.library.OfflineChanges
import com.qtekfun.ultimatetunes.core.player.offline.CollectionKind
import com.qtekfun.ultimatetunes.playback.OfflineControls
import com.qtekfun.ultimatetunes.ui.model.AlbumTile
import com.qtekfun.ultimatetunes.ui.model.LoadError
import com.qtekfun.ultimatetunes.ui.model.LoadState
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
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** An album with its songs, ready to show. */
data class AlbumContent(
    val album: AlbumTile,
    val artistId: ArtistId?,
    val year: Int?,
    val genre: String?,
    val durationSec: Int,
    val tracks: List<TrackTile>,
    val isFavourite: Boolean
) {
    /** Only library albums can be starred in v1 (SPEC §11, T02). */
    val canFavourite: Boolean get() = !album.isExternal
}

/** What the album screen shows. */
data class AlbumUiState(
    val content: LoadState<AlbumContent> = LoadState.Loading,
    /** A favourite change that failed; shown once, then [AlbumViewModel.dismissMessage]. */
    val message: LoadError? = null,
    /** Kept on the phone, in sync with the server (RF-12). */
    val isOffline: Boolean = false
)

/**
 * An album, from the library or from YouTube Music (`ytalbum:` ids, whose songs are "not in
 * library yet"). A library album shows from the local catalog, with no connection too; the server
 * (`getAlbum`) refreshes it, and a refresh that fails keeps what shows. It can be kept offline
 * (RF-12): its songs download and stay in sync.
 */
@HiltViewModel
class AlbumViewModel @Inject constructor(
    savedStateHandle: SavedStateHandle,
    private val api: TunesApi,
    private val offline: OfflineControls,
    repository: LibraryRepository,
    sync: CatalogSync,
    private val changes: OfflineChanges
) : ViewModel() {
    private val id = AlbumId(checkNotNull(savedStateHandle.get<String>(ARG_ID)))

    private val mutableState = MutableStateFlow(AlbumUiState())
    val state: StateFlow<AlbumUiState> = mutableState.asStateFlow()

    private var loading: Job? = null

    /** The server's answer shows: the catalog, which may be older, no longer replaces it. */
    private var answered = false

    /** Stars tapped on this screen: a read running across a tap does not know of it. */
    private var taps = 0

    val refresher = Refresher(viewModelScope) {
        sync.sync()
        read()
    }

    init {
        viewModelScope.launch {
            repository.album(id).collect { album ->
                // A favourite album outside the library has no songs here: only the server has.
                if (!answered && album != null && album.song.isNotEmpty()) {
                    mutableState.update { it.copy(content = LoadState.Ready(album.toContent())) }
                }
            }
        }
        viewModelScope.launch {
            offline.selection.collect { selection ->
                val kept = selection.keepsCollection(CollectionKind.ALBUM, id.value)
                mutableState.update { it.copy(isOffline = kept) }
            }
        }
        load()
    }

    fun load() {
        if (loading?.isActive == true) return
        mutableState.update {
            val kept = it.content as? LoadState.Ready
            it.copy(content = kept ?: LoadState.Loading, message = null)
        }
        loading = viewModelScope.launch { read() }
    }

    /** Asks the server for the album; why that failed, or null. */
    private suspend fun read(): LoadError? {
        val tapsBefore = taps
        return when (val result = api.album(id)) {
            is TunesResult.Success -> {
                show(result.value, tapsBefore)
                null
            }

            is TunesResult.Failure -> keep(result.toLoadError())
        }
    }

    private suspend fun show(album: Album, tapsBefore: Int) {
        answered = true
        // A star not sent yet is newer than what the server says.
        val pending = changes.status.first().albumFavourites[id]
        mutableState.update {
            val content = album.toContent()
            // And one tapped since the read began, maybe not stored yet, is newer than both.
            val shown = (it.content as? LoadState.Ready)?.value?.isFavourite
            val tapped = shown.takeIf { taps != tapsBefore }
            it.copy(
                content = LoadState.Ready(
                    content.copy(isFavourite = tapped ?: pending ?: content.isFavourite)
                )
            )
        }
    }

    /** A read that failed keeps what shows. */
    private fun keep(error: LoadError): LoadError {
        mutableState.update {
            if (it.content is LoadState.Ready) it else it.copy(content = LoadState.Failed(error))
        }
        return error
    }

    private fun Album.toContent(): AlbumContent {
        val albumArtist = displayArtist ?: artist.orEmpty()
        return AlbumContent(
            album = toTile(api),
            artistId = artistId,
            year = year,
            genre = genre,
            durationSec = duration,
            tracks = song.map { song ->
                song.toTile(api, fallbackArtist = albumArtist).let { tile ->
                    tile.copy(albumArtist = tile.albumArtist ?: albumArtist.ifEmpty { null })
                }
            },
            isFavourite = starred != null
        )
    }

    /** Keeps the album on the phone, or stops keeping it. */
    fun toggleOffline() {
        val album = (mutableState.value.content as? LoadState.Ready)?.value ?: return
        val kept = mutableState.value.isOffline
        viewModelScope.launch {
            if (kept) {
                offline.dropCollection(CollectionKind.ALBUM, id.value)
            } else {
                offline.keepCollection(CollectionKind.ALBUM, id.value, album.album.title)
            }
        }
    }

    /** Stars or unstars the album, showing the change at once; it is sent when it can be. */
    fun toggleFavourite() {
        val current = (mutableState.value.content as? LoadState.Ready)?.value ?: return
        if (!current.canFavourite) return
        val favourite = !current.isFavourite
        taps++
        setFavourite(favourite)
        viewModelScope.launch {
            if (!changes.setAlbumFavourite(id, favourite)) {
                setFavourite(!favourite)
                mutableState.value = mutableState.value.copy(message = LoadError.STORAGE)
            }
        }
    }

    fun dismissMessage() {
        mutableState.value = mutableState.value.copy(message = null)
    }

    private fun setFavourite(value: Boolean) {
        val state = mutableState.value
        val ready = state.content as? LoadState.Ready ?: return
        mutableState.value =
            state.copy(content = LoadState.Ready(ready.value.copy(isFavourite = value)))
    }

    companion object {
        /** Navigation argument: the album id. */
        const val ARG_ID = "albumId"
    }
}
