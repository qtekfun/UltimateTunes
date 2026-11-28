// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.search

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.tooling.preview.Preview
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.availability.Availability
import com.qtekfun.ultimatetunes.ui.designsystem.ArtistRow
import com.qtekfun.ultimatetunes.ui.designsystem.ErrorState
import com.qtekfun.ultimatetunes.ui.designsystem.ItemRow
import com.qtekfun.ultimatetunes.ui.designsystem.LoadingState
import com.qtekfun.ultimatetunes.ui.designsystem.LocalAvailability
import com.qtekfun.ultimatetunes.ui.designsystem.MessageState
import com.qtekfun.ultimatetunes.ui.designsystem.ScreenScaffold
import com.qtekfun.ultimatetunes.ui.designsystem.SectionHeader
import com.qtekfun.ultimatetunes.ui.designsystem.TrackRow
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.navigation.Navigator
import com.qtekfun.ultimatetunes.ui.preview.PreviewData
import com.qtekfun.ultimatetunes.ui.theme.Dimens
import com.qtekfun.ultimatetunes.ui.theme.UltimateTunesTheme

/** Test tags of the Search tab. */
const val SEARCH_FIELD_TAG = "search.field"
const val SEARCH_LIST_TAG = "search.list"
const val SEARCH_NOTICE_TAG = "search.notice"

@Composable
fun SearchRoute(
    contentPadding: PaddingValues,
    navigator: Navigator,
    viewModel: SearchViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val recentQueries by viewModel.recentSearches.collectAsStateWithLifecycle()
    SearchScreen(
        state = state,
        contentPadding = contentPadding,
        onQueryChange = viewModel::onQueryChange,
        onSearch = viewModel::submit,
        navigator = navigator,
        recents = RecentSearches(
            queries = recentQueries,
            onRun = viewModel::runRecent,
            onRemove = viewModel::removeRecent,
            onClear = viewModel::clearRecents,
            onResultOpened = viewModel::remember
        )
    )
}

/** Search (RF-03): one list of artists, albums and songs; YouTube Music items marked. */
@Composable
fun SearchScreen(
    state: SearchUiState,
    contentPadding: PaddingValues,
    onQueryChange: (String) -> Unit,
    onSearch: () -> Unit,
    navigator: Navigator,
    modifier: Modifier = Modifier,
    recents: RecentSearches = RecentSearches()
) {
    val availability = LocalAvailability.current
    val opening = remember(navigator, recents.onResultOpened) {
        navigator.remembering(recents.onResultOpened)
    }
    ScreenScaffold(title = stringResource(R.string.tab_search), modifier = modifier) { inner ->
        LazyColumn(
            modifier = Modifier.fillMaxSize().testTag(SEARCH_LIST_TAG),
            contentPadding = PaddingValues(
                top = inner.calculateTopPadding(),
                bottom = contentPadding.calculateBottomPadding() + Dimens.SpaceXL
            )
        ) {
            item { SearchField(state.query, onQueryChange, onSearch) }
            if (state.searching) {
                item {
                    LinearProgressIndicator(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = Dimens.ScreenMargin)
                    )
                }
            }
            state.notice?.let { item { SearchNoticeCard(it, onSearch) } }
            if (state.query.isBlank() && recents.queries.isNotEmpty()) {
                recentSearches(recents)
                return@LazyColumn
            }
            when (val results = state.results) {
                null -> item {
                    MessageState(
                        message = stringResource(R.string.search_hint),
                        icon = R.drawable.ic_search
                    )
                }

                LoadState.Loading -> item { LoadingState() }

                is LoadState.Failed -> item { ErrorState(results.error, onSearch) }

                is LoadState.Ready ->
                    results(results.value.shownWith(availability), opening)
            }
        }
    }
}

/** This navigator, calling [onOpened] before a result opens or plays. */
private fun Navigator.remembering(onOpened: () -> Unit) = copy(
    play = { tracks, index ->
        onOpened()
        play(tracks, index)
    },
    openAlbum = {
        onOpened()
        openAlbum(it)
    },
    openArtist = {
        onOpened()
        openArtist(it)
    }
)

/** In offline mode, only what the phone can play; with no connection, that comes first. */
private fun SearchContent.shownWith(availability: Availability) = SearchContent(
    artists = artists.filter { availability.showsArtist(it.id) }
        .sortedByDescending { availability.canPlayArtist(it.id) },
    albums = albums.filter { availability.showsAlbum(it.id) }
        .sortedByDescending { availability.canPlayAlbum(it.id) },
    tracks = tracks.filter { availability.shows(it.id) }
        .sortedByDescending { availability.canPlay(it.id) }
)

/** Says that the results are the phone's alone, and offers to ask the server again. */
@Composable
private fun SearchNoticeCard(notice: SearchNotice, onRetry: () -> Unit) {
    Surface(
        shape = Dimens.CardShape,
        color = MaterialTheme.colorScheme.surfaceContainerHigh,
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = Dimens.ScreenMargin, vertical = Dimens.SpaceS)
            .testTag(SEARCH_NOTICE_TAG)
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier.padding(horizontal = Dimens.SpaceM, vertical = Dimens.SpaceS)
        ) {
            Text(
                text = stringResource(
                    when (notice) {
                        SearchNotice.NO_CONNECTION -> R.string.search_notice_no_connection
                        SearchNotice.SERVER_UNREACHABLE -> R.string.search_notice_unreachable
                        SearchNotice.OFFLINE_MODE -> R.string.search_notice_offline_mode
                    }
                ),
                style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.weight(1f)
            )
            if (notice == SearchNotice.SERVER_UNREACHABLE) {
                TextButton(onClick = onRetry) { Text(stringResource(R.string.search_retry)) }
            }
        }
    }
}

@Composable
private fun SearchField(query: String, onQueryChange: (String) -> Unit, onSearch: () -> Unit) {
    val focus = LocalFocusManager.current
    OutlinedTextField(
        value = query,
        onValueChange = onQueryChange,
        placeholder = { Text(stringResource(R.string.search_field)) },
        leadingIcon = {
            Icon(painter = painterResource(R.drawable.ic_search), contentDescription = null)
        },
        trailingIcon = {
            if (query.isNotEmpty()) {
                IconButton(onClick = { onQueryChange("") }) {
                    Icon(
                        painter = painterResource(R.drawable.ic_close),
                        contentDescription = stringResource(R.string.search_clear)
                    )
                }
            }
        },
        singleLine = true,
        shape = Dimens.CardShape,
        colors = OutlinedTextFieldDefaults.colors(
            unfocusedContainerColor = MaterialTheme.colorScheme.surfaceContainer,
            focusedContainerColor = MaterialTheme.colorScheme.surfaceContainer
        ),
        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
        keyboardActions = KeyboardActions(
            onSearch = {
                focus.clearFocus()
                onSearch()
            }
        ),
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = Dimens.ScreenMargin, vertical = Dimens.SpaceS)
            .testTag(SEARCH_FIELD_TAG)
    )
}

private fun LazyListScope.results(content: SearchContent, navigator: Navigator) {
    if (content.isEmpty) {
        item {
            MessageState(
                message = stringResource(R.string.search_no_results),
                icon = R.drawable.ic_search
            )
        }
        return
    }
    if (content.artists.isNotEmpty()) {
        item { SectionHeader(stringResource(R.string.search_artists)) }
        itemsIndexed(content.artists, key = { i, a -> "artist-$i-${a.id.value}" }) { i, artist ->
            ArtistRow(
                artist = artist,
                onClick = { navigator.openArtist(artist.id) },
                showDivider = i < content.artists.lastIndex
            )
        }
    }
    if (content.albums.isNotEmpty()) {
        item { SectionHeader(stringResource(R.string.search_albums)) }
        itemsIndexed(content.albums, key = { i, a -> "album-$i-${a.id.value}" }) { i, album ->
            ItemRow(
                title = album.title,
                subtitle = album.artist,
                artworkUrl = album.coverUrl,
                placeholderKey = album.id.value,
                isExternal = album.isExternal,
                onClick = { navigator.openAlbum(album.id) },
                showDivider = i < content.albums.lastIndex,
                available = LocalAvailability.current.canPlayAlbum(album.id)
            )
        }
    }
    if (content.tracks.isNotEmpty()) {
        item { SectionHeader(stringResource(R.string.search_songs)) }
        itemsIndexed(content.tracks, key = { i, t -> "track-$i-${t.id.value}" }) { i, track ->
            TrackRow(
                track = track,
                onClick = { navigator.play(content.tracks, i) },
                showDivider = i < content.tracks.lastIndex
            )
        }
    }
}

@Preview(name = "Search, light", showBackground = true, heightDp = 1200)
@Preview(
    name = "Search, dark, large font",
    showBackground = true,
    heightDp = 1200,
    fontScale = 1.5f,
    uiMode = android.content.res.Configuration.UI_MODE_NIGHT_YES
)
@Composable
private fun SearchPreview() {
    UltimateTunesTheme {
        SearchScreen(
            state = SearchUiState(
                query = "lanterns",
                results = LoadState.Ready(PreviewData.search)
            ),
            contentPadding = PaddingValues(),
            onQueryChange = {},
            onSearch = {},
            navigator = Navigator()
        )
    }
}
