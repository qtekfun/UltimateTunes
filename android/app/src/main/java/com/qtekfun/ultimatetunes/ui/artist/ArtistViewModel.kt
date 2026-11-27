// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.artist

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.model.Artist
import com.qtekfun.ultimatetunes.core.api.model.ArtistId
import com.qtekfun.ultimatetunes.core.library.CatalogSync
import com.qtekfun.ultimatetunes.core.library.LibraryRepository
import com.qtekfun.ultimatetunes.ui.model.AlbumTile
import com.qtekfun.ultimatetunes.ui.model.ArtistTile
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
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** An artist and their albums, newest first. */
data class ArtistContent(
    val artist: ArtistTile,
    val albums: List<AlbumTile>,
    /** The artist's library songs, shown when they have no albums of their own. */
    val songs: List<TrackTile> = emptyList()
)

/**
 * An artist: a library one from the local catalog, refreshed from the server (`getArtist`), or a
 * `ytartist:` one answered from YouTube Music. A refresh that fails keeps what shows.
 */
@HiltViewModel
class ArtistViewModel @Inject constructor(
    savedStateHandle: SavedStateHandle,
    private val api: TunesApi,
    repository: LibraryRepository,
    sync: CatalogSync
) : ViewModel() {
    private val id = ArtistId(checkNotNull(savedStateHandle.get<String>(ARG_ID)))

    /** What the server answered; while null, the catalog's copy shows. */
    private val server = MutableStateFlow<LoadState<ArtistContent>>(LoadState.Loading)

    private var loading: Job? = null

    val refresher = Refresher(viewModelScope) {
        sync.sync()
        read()
    }

    val state: StateFlow<LoadState<ArtistContent>> = combine(
        server,
        repository.artist(id),
        repository.artistSongs(id)
    ) { answered, stored, songs ->
        val tiles = songs.map { it.toTile(api) }
        when {
            answered is LoadState.Ready -> LoadState.Ready(answered.value.withSongs(tiles))
            stored != null -> LoadState.Ready(stored.toContent().withSongs(tiles))
            else -> answered
        }
    }.stateIn(viewModelScope, SharingStarted.Eagerly, LoadState.Loading)

    init {
        load()
    }

    fun load() {
        if (loading?.isActive == true) return
        if (server.value !is LoadState.Ready) server.value = LoadState.Loading
        loading = viewModelScope.launch { read() }
    }

    private suspend fun read(): LoadError? = when (val result = api.artist(id)) {
        is TunesResult.Success -> {
            server.value = LoadState.Ready(result.value.toContent())
            null
        }

        is TunesResult.Failure -> {
            val error = result.toLoadError()
            server.update { if (it is LoadState.Ready) it else LoadState.Failed(error) }
            error
        }
    }

    private fun Artist.toContent() = ArtistContent(
        artist = toTile(api),
        albums = album
            .sortedByDescending { it.year ?: Int.MIN_VALUE }
            .map { it.toTile(api) }
    )

    private fun ArtistContent.withSongs(songs: List<TrackTile>) =
        if (albums.isEmpty()) copy(songs = songs) else this

    companion object {
        /** Navigation argument: the artist id. */
        const val ARG_ID = "artistId"
    }
}
