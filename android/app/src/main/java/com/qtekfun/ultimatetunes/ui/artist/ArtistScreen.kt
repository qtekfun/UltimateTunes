// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.artist

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.ui.designsystem.Artwork
import com.qtekfun.ultimatetunes.ui.designsystem.ErrorState
import com.qtekfun.ultimatetunes.ui.designsystem.LargeTitleScaffold
import com.qtekfun.ultimatetunes.ui.designsystem.LoadingState
import com.qtekfun.ultimatetunes.ui.designsystem.MessageState
import com.qtekfun.ultimatetunes.ui.designsystem.SectionHeader
import com.qtekfun.ultimatetunes.ui.designsystem.albumGrid
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.navigation.Navigator
import com.qtekfun.ultimatetunes.ui.preview.PreviewData
import com.qtekfun.ultimatetunes.ui.theme.Dimens
import com.qtekfun.ultimatetunes.ui.theme.UltimateTunesTheme

@Composable
fun ArtistRoute(
    contentPadding: PaddingValues,
    navigator: Navigator,
    viewModel: ArtistViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    ArtistScreen(state, contentPadding, navigator, onRetry = viewModel::load)
}

/** An artist: round picture and a grid of their albums. */
@Composable
fun ArtistScreen(
    state: LoadState<ArtistContent>,
    contentPadding: PaddingValues,
    navigator: Navigator,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier
) {
    val title = (state as? LoadState.Ready)?.value?.artist?.name.orEmpty()
    LargeTitleScaffold(title = title, onBack = navigator.back, modifier = modifier) { inner ->
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(
                top = inner.calculateTopPadding(),
                bottom = contentPadding.calculateBottomPadding() + Dimens.SpaceXL
            )
        ) {
            when (state) {
                LoadState.Loading -> item { LoadingState() }

                is LoadState.Failed -> item { ErrorState(state.error, onRetry) }

                is LoadState.Ready -> {
                    val artist = state.value
                    item { ArtistHeader(artist) }
                    if (artist.albums.isEmpty()) {
                        item {
                            MessageState(
                                message = stringResource(R.string.artist_no_albums),
                                icon = R.drawable.ic_album
                            )
                        }
                    } else {
                        item { SectionHeader(stringResource(R.string.artist_albums)) }
                        albumGrid(artist.albums, keyPrefix = "albums") {
                            navigator.openAlbum(it.id)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun ArtistHeader(artist: ArtistContent) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(Dimens.SpaceS)
    ) {
        Artwork(
            url = artist.artist.coverUrl,
            placeholderKey = artist.artist.id.value,
            shape = CircleShape,
            modifier = Modifier
                .fillMaxWidth(fraction = 0.5f)
                .widthIn(max = 220.dp)
                .aspectRatio(1f)
        )
        if (artist.artist.isExternal) {
            Text(
                text = stringResource(R.string.artist_external),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(horizontal = Dimens.ScreenMargin)
            )
        }
    }
}

@Preview(name = "Artist", showBackground = true, heightDp = 1000)
@Preview(
    name = "Artist, dark",
    showBackground = true,
    heightDp = 1000,
    uiMode = android.content.res.Configuration.UI_MODE_NIGHT_YES
)
@Composable
private fun ArtistPreview() {
    UltimateTunesTheme {
        ArtistScreen(
            state = LoadState.Ready(PreviewData.artist),
            contentPadding = PaddingValues(),
            navigator = Navigator(),
            onRetry = {}
        )
    }
}
