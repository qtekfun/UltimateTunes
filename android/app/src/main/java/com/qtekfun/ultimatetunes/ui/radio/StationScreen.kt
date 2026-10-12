// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.radio

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
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
import com.qtekfun.ultimatetunes.ui.designsystem.SectionHeader
import com.qtekfun.ultimatetunes.ui.designsystem.TrackRow
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import com.qtekfun.ultimatetunes.ui.preview.PreviewData
import com.qtekfun.ultimatetunes.ui.theme.Dimens
import com.qtekfun.ultimatetunes.ui.theme.UltimateTunesTheme

/** Test tag of a station's Play button. */
const val STATION_PLAY_TAG = "station.play"

@Composable
fun StationRoute(
    contentPadding: PaddingValues,
    onBack: () -> Unit,
    onPlay: (List<TrackTile>, Int) -> Unit,
    viewModel: StationViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    StationScreen(
        state = state,
        contentPadding = contentPadding,
        onBack = onBack,
        onRetry = viewModel::load,
        onPlay = onPlay
    )
}

/** A station: its seed's artwork, Play, and the songs up next (`GET /ut/v1/radio`). */
@Composable
fun StationScreen(
    state: LoadState<StationContent>,
    contentPadding: PaddingValues,
    onBack: () -> Unit,
    onRetry: () -> Unit,
    onPlay: (List<TrackTile>, Int) -> Unit,
    modifier: Modifier = Modifier
) {
    val title = (state as? LoadState.Ready)?.value?.seed?.title.orEmpty()
    LargeTitleScaffold(title = title, onBack = onBack, modifier = modifier) { inner ->
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
                    val station = state.value
                    item { StationHeader(station, onPlay = { onPlay(station.queue, 0) }) }
                    if (station.upNext.isNotEmpty()) {
                        item { SectionHeader(stringResource(R.string.station_up_next)) }
                    }
                    itemsIndexed(station.upNext, key = { _, t -> t.id.value }) { index, track ->
                        TrackRow(
                            track = track,
                            // The queue starts with the seed, so up-next index i is queue index i + 1.
                            onClick = { onPlay(station.queue, index + 1) },
                            showDivider = index < station.upNext.lastIndex
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun StationHeader(station: StationContent, onPlay: () -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = Dimens.ScreenMargin),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(Dimens.SpaceM)
    ) {
        Artwork(
            url = station.seed.coverUrl,
            placeholderKey = station.seed.id.value,
            shape = Dimens.CardShape,
            modifier = Modifier
                .widthIn(max = 280.dp)
                .fillMaxWidth(fraction = 0.7f)
                .aspectRatio(1f)
        )
        Text(
            text = stringResource(R.string.station_label),
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.primary
        )
        Text(
            text = station.seed.artist,
            style = MaterialTheme.typography.bodyLarge,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center
        )
        Button(
            onClick = onPlay,
            shape = Dimens.PillShape,
            modifier = Modifier
                .widthIn(min = 160.dp)
                .heightIn(min = 48.dp)
                .testTag(STATION_PLAY_TAG)
        ) {
            Icon(
                painter = painterResource(R.drawable.ic_play),
                contentDescription = null,
                modifier = Modifier.padding(end = Dimens.SpaceS)
            )
            Text(stringResource(R.string.station_play))
        }
    }
}

@Preview(name = "Station, light", showBackground = true, heightDp = 1000)
@Preview(
    name = "Station, dark",
    showBackground = true,
    heightDp = 1000,
    uiMode = android.content.res.Configuration.UI_MODE_NIGHT_YES
)
@Composable
private fun StationPreview() {
    UltimateTunesTheme {
        StationScreen(
            state = LoadState.Ready(PreviewData.station),
            contentPadding = PaddingValues(),
            onBack = {},
            onRetry = {},
            onPlay = { _, _ -> }
        )
    }
}
