// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.album

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.ArtistId
import com.qtekfun.ultimatetunes.core.player.offline.CollectionKind
import com.qtekfun.ultimatetunes.playback.OfflineControls
import com.qtekfun.ultimatetunes.ui.model.AlbumTile
import com.qtekfun.ultimatetunes.ui.model.LoadError
import com.qtekfun.ultimatetunes.ui.model.LoadState
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
 * An album (`getAlbum`), from the library or from YouTube Music (`ytalbum:` ids, whose songs are
 * "not in library yet"). Opened from Listen Now, Search, an artist or the Library. It can be kept
 * offline (RF-12): its songs download and stay in sync.
 */
@HiltViewModel
class AlbumViewModel @Inject constructor(
    savedStateHandle: SavedStateHandle,
    private val api: TunesApi,
    private val offline: OfflineControls
) : ViewModel() {
    private val id = AlbumId(checkNotNull(savedStateHandle.get<String>(ARG_ID)))

    private val mutableState = MutableStateFlow(AlbumUiState())
    val state: StateFlow<AlbumUiState> = mutableState.asStateFlow()

    private var loading: Job? = null

    init {
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
        mutableState.update { it.copy(content = LoadState.Loading, message = null) }
        loading = viewModelScope.launch {
            val content = loadStateOf(api.album(id)) { album ->
                val artist = album.displayArtist ?: album.artist.orEmpty()
                AlbumContent(
                    album = album.toTile(api),
                    artistId = album.artistId,
                    year = album.year,
                    genre = album.genre,
                    durationSec = album.duration,
                    tracks = album.song.map { it.toTile(api, fallbackArtist = artist) },
                    isFavourite = album.starred != null
                )
            }
            mutableState.update { it.copy(content = content) }
        }
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

    /** Stars or unstars the album, showing the change at once and undoing it if it fails. */
    fun toggleFavourite() {
        val current = (mutableState.value.content as? LoadState.Ready)?.value ?: return
        if (!current.canFavourite) return
        val favourite = !current.isFavourite
        setFavourite(favourite)
        viewModelScope.launch {
            val result = if (favourite) {
                api.star(albumIds = listOf(id))
            } else {
                api.unstar(albumIds = listOf(id))
            }
            if (result is TunesResult.Failure) {
                setFavourite(!favourite)
                mutableState.value = mutableState.value.copy(message = result.toLoadError())
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
