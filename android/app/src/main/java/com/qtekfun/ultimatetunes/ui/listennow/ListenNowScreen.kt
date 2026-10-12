// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.listennow

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.tooling.preview.Preview
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.ui.designsystem.AlbumCard
import com.qtekfun.ultimatetunes.ui.designsystem.ErrorState
import com.qtekfun.ultimatetunes.ui.designsystem.LargeTitleScaffold
import com.qtekfun.ultimatetunes.ui.designsystem.LoadingState
import com.qtekfun.ultimatetunes.ui.designsystem.MessageState
import com.qtekfun.ultimatetunes.ui.designsystem.SectionHeader
import com.qtekfun.ultimatetunes.ui.designsystem.Shelf
import com.qtekfun.ultimatetunes.ui.designsystem.ShelfAlbumCard
import com.qtekfun.ultimatetunes.ui.designsystem.StationCard
import com.qtekfun.ultimatetunes.ui.designsystem.TrackRow
import com.qtekfun.ultimatetunes.ui.model.AlbumTile
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import com.qtekfun.ultimatetunes.ui.preview.PreviewData
import com.qtekfun.ultimatetunes.ui.theme.Dimens
import com.qtekfun.ultimatetunes.ui.theme.UltimateTunesTheme

/** Test tag of the Listen Now list. */
const val LISTEN_NOW_LIST_TAG = "listenNow.list"

@Composable
fun ListenNowRoute(
    contentPadding: PaddingValues,
    onPlay: (List<TrackTile>, Int) -> Unit,
    onOpenStation: (SongId) -> Unit,
    viewModel: ListenNowViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    ListenNowScreen(
        state = state,
        contentPadding = contentPadding,
        onRetry = viewModel::load,
        onPlay = onPlay,
        onOpenStation = onOpenStation
    )
}

/** Listen Now (RF-11): stations, recently played, top songs and a grid of recent additions. */
@Composable
fun ListenNowScreen(
    state: LoadState<ListenNowContent>,
    contentPadding: PaddingValues,
    onRetry: () -> Unit,
    onPlay: (List<TrackTile>, Int) -> Unit,
    onOpenStation: (SongId) -> Unit,
    modifier: Modifier = Modifier
) {
    LargeTitleScaffold(
        title = stringResource(R.string.tab_listen_now),
        modifier = modifier
    ) { inner ->
        LazyColumn(
            modifier = Modifier.fillMaxSize().testTag(LISTEN_NOW_LIST_TAG),
            contentPadding = PaddingValues(
                top = inner.calculateTopPadding(),
                bottom = contentPadding.calculateBottomPadding() + Dimens.SpaceXL
            )
        ) {
            when (state) {
                LoadState.Loading -> item { LoadingState() }
                is LoadState.Failed -> item { ErrorState(state.error, onRetry) }
                is LoadState.Ready -> content(state.value, onPlay, onOpenStation)
            }
        }
    }
}

private fun LazyListScope.content(
    content: ListenNowContent,
    onPlay: (List<TrackTile>, Int) -> Unit,
    onOpenStation: (SongId) -> Unit
) {
    if (content.isEmpty) {
        item {
            MessageState(
                message = stringResource(R.string.listen_now_empty),
                icon = R.drawable.ic_listen_now
            )
        }
        return
    }
    if (content.stations.isNotEmpty()) {
        item { SectionHeader(stringResource(R.string.listen_now_stations)) }
        item {
            Shelf(content.stations) { station ->
                StationCard(
                    station = station,
                    onClick = { onOpenStation(station.seedId) },
                    modifier = Modifier.width(Dimens.StationTile)
                )
            }
        }
    }
    if (content.recentlyPlayed.isNotEmpty()) {
        item { SectionHeader(stringResource(R.string.listen_now_recently_played)) }
        item {
            Shelf(content.recentlyPlayed) { ShelfAlbumCard(it) }
        }
    }
    if (content.mostPlayed.isNotEmpty()) {
        item { SectionHeader(stringResource(R.string.listen_now_top_songs)) }
        itemsIndexed(content.mostPlayed, key = { _, track ->
            "top-${track.id.value}"
        }) { index, track ->
            TrackRow(
                track = track,
                onClick = { onPlay(content.mostPlayed, index) },
                showDivider = index < content.mostPlayed.lastIndex
            )
        }
    }
    if (content.recentlyAdded.isNotEmpty()) {
        item { SectionHeader(stringResource(R.string.listen_now_recently_added)) }
        artworkGrid(content.recentlyAdded)
    }
}

/** Albums in a two-column grid of large rounded artwork, inside the screen's list. */
private fun LazyListScope.artworkGrid(albums: List<AlbumTile>) {
    val rows = albums.chunked(GRID_COLUMNS)
    itemsIndexed(rows, key = { i, _ -> "grid-$i" }) { _, row ->
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = Dimens.ScreenMargin)
                .padding(bottom = Dimens.SpaceL),
            horizontalArrangement = Arrangement.spacedBy(Dimens.SpaceM)
        ) {
            row.forEach { album -> AlbumCard(album, modifier = Modifier.weight(1f)) }
            repeat(GRID_COLUMNS - row.size) { Spacer(Modifier.weight(1f)) }
        }
    }
}

private const val GRID_COLUMNS = 2

@Preview(name = "Listen Now, light", showBackground = true, heightDp = 1400)
@Preview(
    name = "Listen Now, dark",
    showBackground = true,
    heightDp = 1400,
    uiMode = android.content.res.Configuration.UI_MODE_NIGHT_YES
)
@Composable
private fun ListenNowPreview() {
    UltimateTunesTheme {
        ListenNowScreen(
            state = LoadState.Ready(PreviewData.listenNow),
            contentPadding = PaddingValues(),
            onRetry = {},
            onPlay = { _, _ -> },
            onOpenStation = {}
        )
    }
}

@Preview(name = "Listen Now, error, large font", showBackground = true, fontScale = 1.5f)
@Composable
private fun ListenNowErrorPreview() {
    UltimateTunesTheme {
        ListenNowScreen(
            state = LoadState.Failed(com.qtekfun.ultimatetunes.ui.model.LoadError.NETWORK),
            contentPadding = PaddingValues(),
            onRetry = {},
            onPlay = { _, _ -> },
            onOpenStation = {}
        )
    }
}
