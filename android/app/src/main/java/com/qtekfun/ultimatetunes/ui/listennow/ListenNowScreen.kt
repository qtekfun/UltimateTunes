// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.listennow

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
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
import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.ui.designsystem.ErrorState
import com.qtekfun.ultimatetunes.ui.designsystem.LargeTitleScaffold
import com.qtekfun.ultimatetunes.ui.designsystem.LoadingState
import com.qtekfun.ultimatetunes.ui.designsystem.MenuRow
import com.qtekfun.ultimatetunes.ui.designsystem.MessageState
import com.qtekfun.ultimatetunes.ui.designsystem.SectionHeader
import com.qtekfun.ultimatetunes.ui.designsystem.Shelf
import com.qtekfun.ultimatetunes.ui.designsystem.ShelfAlbumCard
import com.qtekfun.ultimatetunes.ui.designsystem.ShelfTrackCard
import com.qtekfun.ultimatetunes.ui.designsystem.StationCard
import com.qtekfun.ultimatetunes.ui.designsystem.TrackRow
import com.qtekfun.ultimatetunes.ui.designsystem.albumGrid
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import com.qtekfun.ultimatetunes.ui.preview.PreviewData
import com.qtekfun.ultimatetunes.ui.theme.Dimens
import com.qtekfun.ultimatetunes.ui.theme.UltimateTunesTheme

/** Test tag of the Listen Now list. */
const val LISTEN_NOW_LIST_TAG = "listenNow.list"

/** Test tag of the Charts entry on Listen Now. */
const val LISTEN_NOW_CHARTS_TAG = "listenNow.charts"

@Composable
fun ListenNowRoute(
    contentPadding: PaddingValues,
    onPlay: (List<TrackTile>, Int) -> Unit,
    onOpenStation: (SongId) -> Unit,
    onOpenAlbum: (AlbumId) -> Unit,
    onOpenCharts: () -> Unit,
    viewModel: ListenNowViewModel = hiltViewModel(),
    recommendationsViewModel: RecommendationsViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val recommendations by recommendationsViewModel.state.collectAsStateWithLifecycle()
    ListenNowScreen(
        state = state,
        recommendations = recommendations,
        contentPadding = contentPadding,
        onRetry = {
            viewModel.load()
            recommendationsViewModel.load()
        },
        onPlay = onPlay,
        onOpenStation = onOpenStation,
        onOpenCharts = onOpenCharts,
        onOpenAlbum = onOpenAlbum
    )
}

/**
 * Listen Now (RF-11): the "Recommended for You" shelves, a Charts entry, the user's stations,
 * recently played, top songs and a grid of recent additions.
 */
@Composable
fun ListenNowScreen(
    state: LoadState<ListenNowContent>,
    contentPadding: PaddingValues,
    onRetry: () -> Unit,
    onPlay: (List<TrackTile>, Int) -> Unit,
    onOpenStation: (SongId) -> Unit,
    modifier: Modifier = Modifier,
    recommendations: RecommendationsContent? = null,
    onOpenCharts: () -> Unit = {},
    onOpenAlbum: (AlbumId) -> Unit = {}
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

                is LoadState.Ready -> {
                    recommendations?.let { recommendationShelves(it, onPlay) }
                    item {
                        MenuRow(
                            title = stringResource(R.string.listen_now_charts),
                            icon = R.drawable.ic_chart,
                            onClick = onOpenCharts,
                            modifier = Modifier.testTag(LISTEN_NOW_CHARTS_TAG)
                        )
                    }
                    listenNowBody(
                        content = state.value,
                        hasRecommendations = recommendations != null,
                        onPlay = onPlay,
                        onOpenStation = onOpenStation,
                        onOpenAlbum = onOpenAlbum
                    )
                }
            }
        }
    }
}

/** The Listen Now shelves, or a gentle hint when the library is empty and nothing else shows. */
private fun LazyListScope.listenNowBody(
    content: ListenNowContent,
    hasRecommendations: Boolean,
    onPlay: (List<TrackTile>, Int) -> Unit,
    onOpenStation: (SongId) -> Unit,
    onOpenAlbum: (AlbumId) -> Unit
) {
    if (!content.isEmpty) {
        listenNowShelves(content, onPlay, onOpenStation, onOpenAlbum)
    } else if (!hasRecommendations) {
        // Charts stays reachable for a new library; the hint shows only with nothing else.
        item {
            MessageState(
                message = stringResource(R.string.listen_now_empty),
                icon = R.drawable.ic_listen_now
            )
        }
    }
}

private fun LazyListScope.listenNowShelves(
    content: ListenNowContent,
    onPlay: (List<TrackTile>, Int) -> Unit,
    onOpenStation: (SongId) -> Unit,
    onOpenAlbum: (AlbumId) -> Unit
) {
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
            Shelf(content.recentlyPlayed) { ShelfAlbumCard(it, onClick = { onOpenAlbum(it.id) }) }
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
        albumGrid(content.recentlyAdded, keyPrefix = "grid") { onOpenAlbum(it.id) }
    }
}

/** The "Recommended for You" / "Because You Played …" / external-source shelves. */
private fun LazyListScope.recommendationShelves(
    recommendations: RecommendationsContent,
    onPlay: (List<TrackTile>, Int) -> Unit
) {
    if (recommendations.recommendedForYou.isNotEmpty()) {
        item { SectionHeader(stringResource(R.string.listen_now_recommended)) }
        item { TrackShelf(recommendations.recommendedForYou, onPlay) }
    }
    recommendations.becauseYouPlayed.forEach { shelf ->
        item {
            SectionHeader(
                stringResource(R.string.listen_now_because_you_played, shelf.seedTitle)
            )
        }
        item { TrackShelf(shelf.tracks, onPlay) }
    }
    recommendations.sources.forEach { shelf ->
        item { SectionHeader(shelf.title) }
        item { TrackShelf(shelf.tracks, onPlay) }
    }
}

/** A horizontal shelf of songs; tapping one plays [tracks] from that song. */
@Composable
private fun TrackShelf(tracks: List<TrackTile>, onPlay: (List<TrackTile>, Int) -> Unit) {
    Shelf(tracks.withIndex().toList()) { (index, track) ->
        ShelfTrackCard(track = track, onClick = { onPlay(tracks, index) })
    }
}

@Preview(name = "Listen Now, light", showBackground = true, heightDp = 1800)
@Preview(
    name = "Listen Now, dark",
    showBackground = true,
    heightDp = 1800,
    uiMode = android.content.res.Configuration.UI_MODE_NIGHT_YES
)
@Composable
private fun ListenNowPreview() {
    UltimateTunesTheme {
        ListenNowScreen(
            state = LoadState.Ready(PreviewData.listenNow),
            recommendations = PreviewData.recommendations,
            contentPadding = PaddingValues(),
            onRetry = {},
            onPlay = { _, _ -> },
            onOpenStation = {},
            onOpenCharts = {}
        )
    }
}

@Preview(name = "Listen Now, error, large font", showBackground = true, fontScale = 1.5f)
@Composable
private fun ListenNowErrorPreview() {
    UltimateTunesTheme {
        ListenNowScreen(
            state = LoadState.Failed(com.qtekfun.ultimatetunes.ui.model.LoadError.NETWORK),
            recommendations = null,
            contentPadding = PaddingValues(),
            onRetry = {},
            onPlay = { _, _ -> },
            onOpenStation = {},
            onOpenCharts = {}
        )
    }
}
