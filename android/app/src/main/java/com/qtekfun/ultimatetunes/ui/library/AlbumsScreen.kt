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
fun AlbumsRoute(
    contentPadding: PaddingValues,
    navigator: Navigator,
    viewModel: AlbumsViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    AlbumsScreen(state, contentPadding, navigator, onLoadMore = viewModel::loadMore)
}

/** Library › Albums: a grid of every album, by name, loading more near the end. */
@Composable
fun AlbumsScreen(
    state: AlbumsUiState,
    contentPadding: PaddingValues,
    navigator: Navigator,
    onLoadMore: () -> Unit
) {
    LargeTitleScaffold(
        title = stringResource(R.string.library_albums),
        onBack = navigator.back
    ) { inner ->
        LazyVerticalGrid(
            columns = GridCells.Fixed(GRID_COLUMNS),
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(
                start = Dimens.ScreenMargin,
                end = Dimens.ScreenMargin,
                top = inner.calculateTopPadding(),
                bottom = contentPadding.calculateBottomPadding() + Dimens.SpaceXL
            ),
            horizontalArrangement = Arrangement.spacedBy(Dimens.SpaceM),
            verticalArrangement = Arrangement.spacedBy(Dimens.SpaceL)
        ) {
            itemsIndexed(state.albums, key = { _, a -> a.id.value }) { index, album ->
                if (index >= state.albums.size - LOAD_MORE_AHEAD) {
                    LaunchedEffect(state.albums.size) { onLoadMore() }
                }
                AlbumCard(album, onClick = { navigator.openAlbum(album.id) })
            }
            val full = GridItemSpan(GRID_COLUMNS)
            when {
                state.error != null -> item(span = { full }) { ErrorState(state.error, onLoadMore) }
                state.loading -> item(span = { full }) { LoadingState() }
                state.albums.isEmpty() -> item(span = { full }) { EmptyLibrary() }
            }
        }
    }
}

/** How close to the end of the grid the next page is asked for. */
private const val LOAD_MORE_AHEAD = 6

@Preview(name = "Albums, dark", showBackground = true, heightDp = 1000)
@Composable
private fun AlbumsPreview() {
    UltimateTunesTheme(darkTheme = true) {
        AlbumsScreen(
            state = AlbumsUiState(albums = PreviewData.albums, loading = false, hasMore = false),
            contentPadding = PaddingValues(),
            navigator = Navigator(),
            onLoadMore = {}
        )
    }
}
