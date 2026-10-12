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
fun ArtistsRoute(
    contentPadding: PaddingValues,
    navigator: Navigator,
    viewModel: ArtistsViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    ArtistsScreen(state, contentPadding, navigator, onRetry = viewModel::load)
}

/** Library › Artists, under their index letters. */
@Composable
fun ArtistsScreen(
    state: LoadState<List<ArtistSection>>,
    contentPadding: PaddingValues,
    navigator: Navigator,
    onRetry: () -> Unit
) {
    LibraryPageScaffold(stringResource(R.string.library_artists), contentPadding, navigator) {
        when (state) {
            LoadState.Loading -> item { LoadingState() }

            is LoadState.Failed -> item { ErrorState(state.error, onRetry) }

            is LoadState.Ready -> if (state.value.isEmpty()) {
                item { EmptyLibrary() }
            } else {
                state.value.forEach { section ->
                    item(key = "letter-${section.letter}") { LetterHeader(section.letter) }
                    itemsIndexed(
                        section.artists,
                        key = { _, a -> "artist-${a.id.value}" }
                    ) { i, artist ->
                        ArtistRow(
                            artist = artist,
                            onClick = { navigator.openArtist(artist.id) },
                            showDivider = i < section.artists.lastIndex
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun LetterHeader(letter: String) {
    Text(
        text = letter,
        style = MaterialTheme.typography.titleSmall,
        color = MaterialTheme.colorScheme.primary,
        modifier = Modifier
            .padding(horizontal = Dimens.ScreenMargin, vertical = Dimens.SpaceS)
            .semantics { heading() }
    )
}

@Composable
internal fun EmptyLibrary() {
    MessageState(
        message = stringResource(R.string.library_empty),
        icon = R.drawable.ic_library
    )
}
