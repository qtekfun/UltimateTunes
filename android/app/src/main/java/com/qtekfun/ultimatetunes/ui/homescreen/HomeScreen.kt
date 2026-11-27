// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.homescreen

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.ui.designsystem.Artwork
import com.qtekfun.ultimatetunes.ui.designsystem.ErrorState
import com.qtekfun.ultimatetunes.ui.designsystem.LoadingState
import com.qtekfun.ultimatetunes.ui.designsystem.LocalAvailability
import com.qtekfun.ultimatetunes.ui.designsystem.MenuRow
import com.qtekfun.ultimatetunes.ui.designsystem.MessageState
import com.qtekfun.ultimatetunes.ui.designsystem.PageRefresh
import com.qtekfun.ultimatetunes.ui.designsystem.RefreshBox
import com.qtekfun.ultimatetunes.ui.designsystem.ScreenScaffold
import com.qtekfun.ultimatetunes.ui.designsystem.SectionHeader
import com.qtekfun.ultimatetunes.ui.designsystem.Shelf
import com.qtekfun.ultimatetunes.ui.designsystem.ShelfAlbumCard
import com.qtekfun.ultimatetunes.ui.designsystem.ShelfTrackCard
import com.qtekfun.ultimatetunes.ui.designsystem.StationCard
import com.qtekfun.ultimatetunes.ui.designsystem.SyncProblemRow
import com.qtekfun.ultimatetunes.ui.designsystem.TrackRow
import com.qtekfun.ultimatetunes.ui.designsystem.availabilityDescription
import com.qtekfun.ultimatetunes.ui.designsystem.availableOrDimmed
import com.qtekfun.ultimatetunes.ui.designsystem.rememberScreenSnackbar
import com.qtekfun.ultimatetunes.ui.model.AlbumTile
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.model.RefreshState
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import com.qtekfun.ultimatetunes.ui.navigation.LibraryPage
import com.qtekfun.ultimatetunes.ui.navigation.Navigator
import com.qtekfun.ultimatetunes.ui.preview.PreviewData
import com.qtekfun.ultimatetunes.ui.theme.Dimens
import com.qtekfun.ultimatetunes.ui.theme.UltimateTunesTheme

/** Test tags of Home. */
const val HOME_LIST_TAG = "home.list"
const val HOME_CHARTS_TAG = "home.charts"

/** What Home can do besides navigating. */
data class HomeActions(
    val retry: () -> Unit = {},
    val refresh: () -> Unit = {},
    val messageShown: () -> Unit = {}
)

@Composable
fun HomeRoute(
    contentPadding: PaddingValues,
    navigator: Navigator,
    viewModel: HomeViewModel = hiltViewModel(),
    recommendationsViewModel: RecommendationsViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val refresh by viewModel.refresher.state.collectAsStateWithLifecycle()
    val recommendations by recommendationsViewModel.state.collectAsStateWithLifecycle()
    val reload = {
        viewModel.refresher.refresh()
        recommendationsViewModel.load()
    }
    HomeScreen(
        state = state,
        recommendations = recommendations,
        refresh = refresh,
        contentPadding = contentPadding,
        navigator = navigator,
        actions = HomeActions(
            retry = reload,
            refresh = reload,
            messageShown = viewModel.refresher::messageShown
        )
    )
}

/**
 * Home (RF-11): quick access to what was played last, the stations, recommendations and charts,
 * and the library's recent additions and top songs. In offline mode only what the phone can play.
 */
@Composable
fun HomeScreen(
    state: HomeUiState,
    contentPadding: PaddingValues,
    navigator: Navigator,
    actions: HomeActions,
    modifier: Modifier = Modifier,
    recommendations: RecommendationsContent? = null,
    refresh: RefreshState = RefreshState()
) {
    val snackbar = rememberScreenSnackbar()
    ScreenScaffold(
        title = stringResource(R.string.tab_home),
        modifier = modifier,
        snackbarHost = snackbar.host
    ) { inner ->
        val pull = PageRefresh(refresh, actions.refresh, actions.messageShown)
        RefreshBox(pull, inner, snackbar) {
            val offlineMode = LocalAvailability.current.offlineMode
            LazyColumn(
                modifier = Modifier.fillMaxSize().testTag(HOME_LIST_TAG),
                contentPadding = PaddingValues(
                    bottom = contentPadding.calculateBottomPadding() + Dimens.SpaceXL
                )
            ) {
                state.syncError?.let { error ->
                    if (state.content is LoadState.Ready) item { SyncProblemRow(error) }
                }
                when (val content = state.content) {
                    LoadState.Loading -> item { LoadingState() }

                    is LoadState.Failed -> item { ErrorState(content.error, actions.retry) }

                    is LoadState.Ready -> {
                        item { QuickAccess(content.value.quickAccess, navigator) }
                        // Stations, recommendations and charts all come from the server.
                        if (!offlineMode) {
                            stations(content.value, navigator)
                            recommendations?.let { recommendationShelves(it, navigator.play) }
                            charts(navigator.openCharts)
                        }
                        libraryShelves(content.value, navigator)
                        if (content.value.isEmpty && recommendations == null) {
                            item {
                                MessageState(
                                    message = stringResource(R.string.home_empty),
                                    icon = R.drawable.ic_listen_now
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

private fun LazyListScope.stations(content: HomeContent, navigator: Navigator) {
    if (content.stations.isEmpty()) return
    item { SectionHeader(stringResource(R.string.home_stations)) }
    item {
        val online = LocalAvailability.current.online
        Shelf(content.stations) { station ->
            StationCard(
                station = station,
                onClick = { navigator.openStation(station.seedId) },
                available = online
            )
        }
    }
}

private fun LazyListScope.charts(onOpen: () -> Unit) {
    item { SectionHeader(stringResource(R.string.home_charts)) }
    item {
        MenuRow(
            title = stringResource(R.string.charts_title),
            icon = R.drawable.ic_chart,
            onClick = onOpen,
            modifier = Modifier.testTag(HOME_CHARTS_TAG)
        )
    }
}

private fun LazyListScope.libraryShelves(content: HomeContent, navigator: Navigator) {
    if (content.recentlyAdded.isNotEmpty()) {
        item { SectionHeader(stringResource(R.string.home_recently_added)) }
        item {
            val availability = LocalAvailability.current
            Shelf(content.recentlyAdded.filter { availability.showsAlbum(it.id) }) {
                ShelfAlbumCard(it, onClick = { navigator.openAlbum(it.id) })
            }
        }
    }
    if (content.mostPlayed.isNotEmpty()) {
        item { SectionHeader(stringResource(R.string.home_top_songs)) }
        itemsIndexed(content.mostPlayed, key = { _, t -> "top-${t.id.value}" }) { index, track ->
            if (LocalAvailability.current.shows(track.id)) {
                TrackRow(
                    track = track,
                    onClick = { navigator.play(content.mostPlayed, index) },
                    showDivider = index < content.mostPlayed.lastIndex
                )
            }
        }
    }
}

/** The "Recommended for You" / "Because You Played …" / external-source shelves. */
private fun LazyListScope.recommendationShelves(
    recommendations: RecommendationsContent,
    onPlay: (List<TrackTile>, Int) -> Unit
) {
    if (recommendations.recommendedForYou.isNotEmpty()) {
        item { SectionHeader(stringResource(R.string.home_recommended)) }
        item { TrackShelf(recommendations.recommendedForYou, onPlay) }
    }
    recommendations.becauseYouPlayed.forEach { shelf ->
        item {
            SectionHeader(stringResource(R.string.home_because_you_played, shelf.seedTitle))
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

@Preview(name = "Home, light", showBackground = true, heightDp = 1800)
@Preview(
    name = "Home, dark",
    showBackground = true,
    heightDp = 1800,
    uiMode = android.content.res.Configuration.UI_MODE_NIGHT_YES
)
@Composable
private fun HomePreview() {
    UltimateTunesTheme {
        HomeScreen(
            state = HomeUiState(LoadState.Ready(PreviewData.home)),
            recommendations = PreviewData.recommendations,
            contentPadding = PaddingValues(),
            navigator = Navigator(),
            actions = HomeActions()
        )
    }
}

@Preview(name = "Home, error, large font", showBackground = true, fontScale = 1.5f)
@Composable
private fun HomeErrorPreview() {
    UltimateTunesTheme {
        HomeScreen(
            state = HomeUiState(
                LoadState.Failed(com.qtekfun.ultimatetunes.ui.model.LoadError.NETWORK)
            ),
            contentPadding = PaddingValues(),
            navigator = Navigator(),
            actions = HomeActions()
        )
    }
}
