// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.radio

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.tooling.preview.Preview
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.ui.designsystem.ErrorState
import com.qtekfun.ultimatetunes.ui.designsystem.LargeTitleScaffold
import com.qtekfun.ultimatetunes.ui.designsystem.LoadingState
import com.qtekfun.ultimatetunes.ui.designsystem.MessageState
import com.qtekfun.ultimatetunes.ui.designsystem.NavigationRow
import com.qtekfun.ultimatetunes.ui.designsystem.SectionHeader
import com.qtekfun.ultimatetunes.ui.designsystem.StationCard
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.preview.PreviewData
import com.qtekfun.ultimatetunes.ui.theme.Dimens
import com.qtekfun.ultimatetunes.ui.theme.UltimateTunesTheme

@Composable
fun RadioRoute(
    contentPadding: PaddingValues,
    onOpenStation: (SongId) -> Unit,
    viewModel: RadioViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    RadioScreen(
        state = state,
        contentPadding = contentPadding,
        onRetry = viewModel::load,
        onOpenStation = onOpenStation
    )
}

/** The Radio tab: the user's stations large, then one station per top song. */
@Composable
fun RadioScreen(
    state: LoadState<RadioContent>,
    contentPadding: PaddingValues,
    onRetry: () -> Unit,
    onOpenStation: (SongId) -> Unit,
    modifier: Modifier = Modifier
) {
    LargeTitleScaffold(title = stringResource(R.string.tab_radio), modifier = modifier) { inner ->
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
                is LoadState.Ready -> stations(state.value, onOpenStation)
            }
        }
    }
}

private fun LazyListScope.stations(content: RadioContent, onOpenStation: (SongId) -> Unit) {
    if (content.isEmpty) {
        item { MessageState(stringResource(R.string.radio_empty), icon = R.drawable.ic_radio) }
        return
    }
    items(content.featured, key = { "featured-${it.seedId.value}" }) { station ->
        StationCard(
            station = station,
            onClick = { onOpenStation(station.seedId) },
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = Dimens.ScreenMargin, vertical = Dimens.SpaceS)
        )
    }
    if (content.fromSongs.isNotEmpty()) {
        item { SectionHeader(stringResource(R.string.radio_from_songs)) }
        items(content.fromSongs, key = { "song-${it.seedId.value}" }) { station ->
            NavigationRow(
                title = station.title,
                subtitle = station.subtitle,
                artworkUrl = station.coverUrl,
                placeholderKey = station.seedId.value,
                onClick = { onOpenStation(station.seedId) },
                contentDescription = stringResource(R.string.station_description, station.title)
            )
        }
    }
}

@Preview(name = "Radio, light", showBackground = true, heightDp = 900)
@Preview(
    name = "Radio, dark",
    showBackground = true,
    heightDp = 900,
    uiMode = android.content.res.Configuration.UI_MODE_NIGHT_YES
)
@Composable
private fun RadioPreview() {
    UltimateTunesTheme {
        RadioScreen(
            state = LoadState.Ready(PreviewData.radio),
            contentPadding = PaddingValues(),
            onRetry = {},
            onOpenStation = {}
        )
    }
}
