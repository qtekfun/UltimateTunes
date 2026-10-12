// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.library

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.itemsIndexed
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.tooling.preview.Preview
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.ui.designsystem.AlbumCard
import com.qtekfun.ultimatetunes.ui.designsystem.ArtistRow
import com.qtekfun.ultimatetunes.ui.designsystem.ErrorState
import com.qtekfun.ultimatetunes.ui.designsystem.GRID_COLUMNS
import com.qtekfun.ultimatetunes.ui.designsystem.LargeTitleScaffold
import com.qtekfun.ultimatetunes.ui.designsystem.LoadingState
import com.qtekfun.ultimatetunes.ui.designsystem.MessageState
import com.qtekfun.ultimatetunes.ui.designsystem.SectionHeader
import com.qtekfun.ultimatetunes.ui.designsystem.Shelf
import com.qtekfun.ultimatetunes.ui.designsystem.ShelfAlbumCard
import com.qtekfun.ultimatetunes.ui.designsystem.TrackRow
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import com.qtekfun.ultimatetunes.ui.navigation.Navigator
import com.qtekfun.ultimatetunes.ui.preview.PreviewData
import com.qtekfun.ultimatetunes.ui.theme.Dimens
import com.qtekfun.ultimatetunes.ui.theme.UltimateTunesTheme

@Composable
fun FavouritesRoute(
    contentPadding: PaddingValues,
    navigator: Navigator,
    viewModel: FavouritesViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    // Loaded each time the page shows, so a heart changed on an album appears here.
    LaunchedEffect(Unit) { viewModel.load() }
    FavouritesScreen(state, contentPadding, navigator, onRetry = viewModel::load)
}

/** Library › Favourites: songs, then albums and artists. */
@Composable
fun FavouritesScreen(
    state: LoadState<FavouritesContent>,
    contentPadding: PaddingValues,
    navigator: Navigator,
    onRetry: () -> Unit
) {
    LibraryPageScaffold(stringResource(R.string.library_favourites), contentPadding, navigator) {
        when (state) {
            LoadState.Loading -> item { LoadingState() }
            is LoadState.Failed -> item { ErrorState(state.error, onRetry) }
            is LoadState.Ready -> favourites(state.value, navigator)
        }
    }
}

private fun LazyListScope.favourites(content: FavouritesContent, navigator: Navigator) {
    if (content.isEmpty) {
        item {
            MessageState(
                message = stringResource(R.string.favourites_empty),
                icon = R.drawable.ic_favorite_border
            )
        }
        return
    }
    if (content.songs.isNotEmpty()) {
        item { SectionHeader(stringResource(R.string.search_songs)) }
        trackList(content.songs, keyPrefix = "song", navigator)
    }
    if (content.albums.isNotEmpty()) {
        item { SectionHeader(stringResource(R.string.search_albums)) }
        item {
            Shelf(content.albums) { album ->
                ShelfAlbumCard(album, onClick = { navigator.openAlbum(album.id) })
            }
        }
    }
    if (content.artists.isNotEmpty()) {
        item { SectionHeader(stringResource(R.string.search_artists)) }
        itemsIndexed(content.artists, key = { _, a -> "artist-${a.id.value}" }) { i, artist ->
            ArtistRow(
                artist = artist,
                onClick = { navigator.openArtist(artist.id) },
                showDivider = i < content.artists.lastIndex
            )
        }
    }
}

/** Songs that play as one queue from the tapped one. */
internal fun LazyListScope.trackList(
    tracks: List<TrackTile>,
    keyPrefix: String,
    navigator: Navigator
) {
    itemsIndexed(tracks, key = { i, t -> "$keyPrefix-$i-${t.id.value}" }) { i, track ->
        TrackRow(
            track = track,
            onClick = { navigator.play(tracks, i) },
            showDivider = i < tracks.lastIndex
        )
    }
}

@Preview(name = "Favourites", showBackground = true, heightDp = 1000)
@Composable
private fun FavouritesPreview() {
    UltimateTunesTheme {
        FavouritesScreen(
            state = LoadState.Ready(
                FavouritesContent(
                    songs = PreviewData.tracks.take(n = 3),
                    albums = PreviewData.albums,
                    artists = listOf(PreviewData.artist.artist)
                )
            ),
            contentPadding = PaddingValues(),
            navigator = Navigator(),
            onRetry = {}
        )
    }
}
