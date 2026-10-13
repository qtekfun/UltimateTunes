// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.charts

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
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
import com.qtekfun.ultimatetunes.ui.designsystem.ErrorState
import com.qtekfun.ultimatetunes.ui.designsystem.LargeTitleScaffold
import com.qtekfun.ultimatetunes.ui.designsystem.LoadingState
import com.qtekfun.ultimatetunes.ui.designsystem.MessageState
import com.qtekfun.ultimatetunes.ui.designsystem.SectionHeader
import com.qtekfun.ultimatetunes.ui.designsystem.TrackRow
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import com.qtekfun.ultimatetunes.ui.preview.PreviewData
import com.qtekfun.ultimatetunes.ui.theme.Dimens
import com.qtekfun.ultimatetunes.ui.theme.UltimateTunesTheme
import java.util.Locale

/** Test tag of the Charts list. */
const val CHARTS_LIST_TAG = "charts.list"

/** Global chart's country code (ISO 3166-1 alpha-2 reserves `ZZ` for "unknown / global"). */
private const val GLOBAL_COUNTRY = "ZZ"

@Composable
fun ChartsRoute(
    contentPadding: PaddingValues,
    onBack: () -> Unit,
    onPlay: (List<TrackTile>, Int) -> Unit,
    viewModel: ChartsViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    ChartsScreen(
        state = state,
        contentPadding = contentPadding,
        onBack = onBack,
        onRetry = viewModel::load,
        onPlay = onPlay
    )
}

/** The Charts list (RF-11): a country's top songs from `GET /ut/v1/charts`, tapped to play. */
@Composable
fun ChartsScreen(
    state: LoadState<ChartsContent>,
    contentPadding: PaddingValues,
    onBack: () -> Unit,
    onRetry: () -> Unit,
    onPlay: (List<TrackTile>, Int) -> Unit,
    modifier: Modifier = Modifier
) {
    LargeTitleScaffold(
        title = stringResource(R.string.charts_title),
        onBack = onBack,
        modifier = modifier
    ) { inner ->
        LazyColumn(
            modifier = Modifier.fillMaxSize().testTag(CHARTS_LIST_TAG),
            contentPadding = PaddingValues(
                top = inner.calculateTopPadding(),
                bottom = contentPadding.calculateBottomPadding() + Dimens.SpaceXL
            )
        ) {
            when (state) {
                LoadState.Loading -> item { LoadingState() }
                is LoadState.Failed -> item { ErrorState(state.error, onRetry) }
                is LoadState.Ready -> charts(state.value, onPlay)
            }
        }
    }
}

private fun LazyListScope.charts(content: ChartsContent, onPlay: (List<TrackTile>, Int) -> Unit) {
    if (content.isEmpty) {
        item { MessageState(stringResource(R.string.charts_empty), icon = R.drawable.ic_chart) }
        return
    }
    item { SectionHeader(stringResource(R.string.charts_country, countryLabel(content.country))) }
    itemsIndexed(content.tracks, key = { i, t -> "$i-${t.id.value}" }) { index, track ->
        TrackRow(
            track = track,
            onClick = { onPlay(content.tracks, index) },
            showDivider = index < content.tracks.lastIndex
        )
    }
}

/** A readable name for the chart's country: "Global" for `ZZ`, else the region's display name. */
@Composable
private fun countryLabel(country: String): String = if (country.equals(GLOBAL_COUNTRY, true)) {
    stringResource(R.string.charts_global)
} else {
    runCatching { Locale.Builder().setRegion(country).build().displayCountry }
        .getOrNull()
        ?.takeIf { it.isNotEmpty() }
        ?: country
}

@Preview(name = "Charts, light", showBackground = true, heightDp = 900)
@Preview(
    name = "Charts, dark",
    showBackground = true,
    heightDp = 900,
    uiMode = android.content.res.Configuration.UI_MODE_NIGHT_YES
)
@Composable
private fun ChartsPreview() {
    UltimateTunesTheme {
        ChartsScreen(
            state = LoadState.Ready(PreviewData.charts),
            contentPadding = PaddingValues(),
            onBack = {},
            onRetry = {},
            onPlay = { _, _ -> }
        )
    }
}
