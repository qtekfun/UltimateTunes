// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.library

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.selectableGroup
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.core.api.model.ArtistId
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import com.qtekfun.ultimatetunes.ui.actions.CollectionOverflow
import com.qtekfun.ultimatetunes.ui.designsystem.AlbumCard
import com.qtekfun.ultimatetunes.ui.designsystem.ArtistRow
import com.qtekfun.ultimatetunes.ui.designsystem.ErrorState
import com.qtekfun.ultimatetunes.ui.designsystem.ItemRow
import com.qtekfun.ultimatetunes.ui.designsystem.LoadingState
import com.qtekfun.ultimatetunes.ui.designsystem.LocalAvailability
import com.qtekfun.ultimatetunes.ui.designsystem.MenuRow
import com.qtekfun.ultimatetunes.ui.designsystem.MessageEffect
import com.qtekfun.ultimatetunes.ui.designsystem.MessageState
import com.qtekfun.ultimatetunes.ui.designsystem.PageRefresh
import com.qtekfun.ultimatetunes.ui.designsystem.RefreshBox
import com.qtekfun.ultimatetunes.ui.designsystem.ScreenScaffold
import com.qtekfun.ultimatetunes.ui.designsystem.SyncProblemRow
import com.qtekfun.ultimatetunes.ui.designsystem.TextInputDialog
import com.qtekfun.ultimatetunes.ui.designsystem.TrackRow
import com.qtekfun.ultimatetunes.ui.designsystem.rememberScreenSnackbar
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.model.PlaylistTile
import com.qtekfun.ultimatetunes.ui.model.RefreshState
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import com.qtekfun.ultimatetunes.ui.navigation.LibraryPage
import com.qtekfun.ultimatetunes.ui.navigation.Navigator
import com.qtekfun.ultimatetunes.ui.preview.PreviewData
import com.qtekfun.ultimatetunes.ui.theme.Dimens
import com.qtekfun.ultimatetunes.ui.theme.UltimateTunesTheme

/** Test tags of the Library tab. */
const val LIBRARY_LIST_TAG = "library.list"
const val LIBRARY_ON_PHONE_TAG = "library.onPhone"
const val LIBRARY_NEW_TAG = "library.new"
const val LIBRARY_IMPORT_TAG = "library.import"
const val NEW_PLAYLIST_TAG = "playlists.new"

fun libraryFilterTag(filter: LibraryFilter): String = "library.filter.${filter.name}"

fun libraryRowTag(page: LibraryPage): String = "library.${page.route}"

/** What the Library can do besides navigating. */
data class LibraryActions(
    val select: (LibraryFilter) -> Unit = {},
    val setOnPhoneOnly: (Boolean) -> Unit = {},
    val refresh: () -> Unit = {},
    val refreshMessageShown: () -> Unit = {},
    val create: (String) -> Unit = {},
    val messageShown: () -> Unit = {},
    val playlistTracks: suspend (PlaylistId) -> List<TrackTile> = { emptyList() },
    val artistTracks: suspend (ArtistId) -> List<TrackTile> = { emptyList() },
    val toggleOffline: (PlaylistTile) -> Unit = {}
)

@Composable
fun LibraryRoute(
    contentPadding: PaddingValues,
    navigator: Navigator,
    viewModel: LibraryViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val refresh by viewModel.refresher.state.collectAsStateWithLifecycle()
    LaunchedEffect(state.newPlaylist.created) {
        state.newPlaylist.created?.let {
            viewModel.onCreatedOpened()
            navigator.openPlaylist(it)
        }
    }
    LibraryScreen(
        state = state,
        contentPadding = contentPadding,
        navigator = navigator,
        refresh = refresh,
        actions = LibraryActions(
            select = viewModel::select,
            setOnPhoneOnly = viewModel::setOnPhoneOnly,
            refresh = viewModel.refresher::refresh,
            refreshMessageShown = viewModel.refresher::messageShown,
            create = viewModel::create,
            messageShown = viewModel::dismissMessage,
            playlistTracks = viewModel::playlistTracks,
            artistTracks = viewModel::artistTracks,
            toggleOffline = viewModel::toggleOffline
        )
    )
}

/**
 * The Library tab: the filter chips and "On this phone", and under them the list itself. The
 * playlists also give access to a new playlist, import, favourites and downloads.
 */
@Composable
fun LibraryScreen(
    state: LibraryUiState,
    contentPadding: PaddingValues,
    navigator: Navigator,
    actions: LibraryActions,
    modifier: Modifier = Modifier,
    refresh: RefreshState = RefreshState()
) {
    var naming by rememberSaveable { mutableStateOf(false) }
    val snackbar = rememberScreenSnackbar()
    MessageEffect(state.newPlaylist.message, snackbar.state, actions.messageShown)
    ScreenScaffold(
        title = stringResource(R.string.tab_library),
        modifier = modifier,
        snackbarHost = snackbar.host
    ) { inner ->
        Column(Modifier.padding(top = inner.calculateTopPadding())) {
            FilterBar(state, actions)
            val pull = PageRefresh(refresh, actions.refresh, actions.refreshMessageShown)
            RefreshBox(pull, PaddingValues(), snackbar) {
                val bottom = contentPadding.calculateBottomPadding() + Dimens.SpaceXL
                val items = (state.items as? LoadState.Ready)?.value
                if (items is LibraryItems.Albums && !items.isEmpty) {
                    AlbumGrid(items, bottom, navigator)
                } else {
                    LazyColumn(
                        modifier = Modifier.fillMaxSize().testTag(LIBRARY_LIST_TAG),
                        contentPadding = PaddingValues(bottom = bottom)
                    ) {
                        library(state, navigator, actions, onNewPlaylist = { naming = true })
                    }
                }
            }
        }
    }
    if (naming) {
        TextInputDialog(
            title = stringResource(R.string.playlist_new),
            label = stringResource(R.string.playlist_name),
            confirmLabel = stringResource(R.string.playlist_create),
            onConfirm = {
                naming = false
                actions.create(it)
            },
            onDismiss = { naming = false }
        )
    }
}

private val LibraryFilter.label: Int
    get() = when (this) {
        LibraryFilter.PLAYLISTS -> R.string.library_playlists
        LibraryFilter.ALBUMS -> R.string.library_albums
        LibraryFilter.ARTISTS -> R.string.library_artists
        LibraryFilter.SONGS -> R.string.library_songs
    }

/** The filters in a row that scrolls with large fonts, and "On this phone" under them. */
@Composable
private fun FilterBar(state: LibraryUiState, actions: LibraryActions) {
    Column(Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier
                .horizontalScroll(rememberScrollState())
                .padding(horizontal = Dimens.ScreenMargin)
                .semantics { selectableGroup() },
            horizontalArrangement = Arrangement.spacedBy(Dimens.SpaceS)
        ) {
            LibraryFilter.entries.forEach { filter ->
                FilterChip(
                    selected = state.filter == filter,
                    onClick = { actions.select(filter) },
                    label = { Text(stringResource(filter.label)) },
                    modifier = Modifier.heightIn(min = 40.dp).testTag(libraryFilterTag(filter))
                )
            }
        }
        FilterChip(
            selected = state.onPhoneOnly,
            // Offline mode shows only the phone's music anyway.
            enabled = !state.offlineMode,
            onClick = { actions.setOnPhoneOnly(!state.onPhoneOnly) },
            label = { Text(stringResource(R.string.library_on_phone)) },
            leadingIcon = {
                Icon(painterResource(R.drawable.ic_download), contentDescription = null)
            },
            modifier = Modifier
                .padding(horizontal = Dimens.ScreenMargin)
                .testTag(LIBRARY_ON_PHONE_TAG)
        )
    }
}

@Composable
private fun AlbumGrid(
    albums: LibraryItems.Albums,
    bottom: androidx.compose.ui.unit.Dp,
    navigator: Navigator
) {
    LazyVerticalGrid(
        columns = GridCells.Adaptive(Dimens.ShelfTile),
        modifier = Modifier.fillMaxSize().testTag(LIBRARY_LIST_TAG),
        contentPadding = PaddingValues(
            start = Dimens.ScreenMargin,
            end = Dimens.ScreenMargin,
            top = Dimens.SpaceS,
            bottom = bottom
        ),
        horizontalArrangement = Arrangement.spacedBy(Dimens.SpaceM),
        verticalArrangement = Arrangement.spacedBy(Dimens.SpaceL)
    ) {
        items(albums.albums, key = { it.id.value }) { album ->
            AlbumCard(album, onClick = { navigator.openAlbum(album.id) })
        }
    }
}

private fun LazyListScope.library(
    state: LibraryUiState,
    navigator: Navigator,
    actions: LibraryActions,
    onNewPlaylist: () -> Unit
) {
    state.syncError?.let { error ->
        if (state.items is LoadState.Ready) item { SyncProblemRow(error) }
    }
    if (state.filter == LibraryFilter.PLAYLISTS) {
        item { NewOrImport(navigator, onNewPlaylist) }
        item { CollectionRows(state, navigator) }
    }
    when (val load = state.items) {
        LoadState.Loading -> item { LoadingState() }

        is LoadState.Failed -> item { ErrorState(load.error, actions.refresh) }

        is LoadState.Ready -> if (load.value.isEmpty) {
            item { EmptyList(load.value.filter, state.onPhoneOnly) }
        } else {
            rows(load.value, state, navigator, actions)
        }
    }
}

private fun LazyListScope.rows(
    items: LibraryItems,
    state: LibraryUiState,
    navigator: Navigator,
    actions: LibraryActions
) {
    when (items) {
        is LibraryItems.Playlists ->
            itemsIndexed(items.playlists, key = { _, p -> p.id.value }) { i, playlist ->
                PlaylistRow(
                    playlist = playlist,
                    isOffline = playlist.id in state.keptPlaylists,
                    showDivider = i < items.playlists.lastIndex,
                    navigator = navigator,
                    actions = actions
                )
            }

        is LibraryItems.Artists ->
            itemsIndexed(items.artists, key = { _, a -> a.id.value }) { i, artist ->
                ArtistRow(
                    artist = artist,
                    onClick = { navigator.openArtist(artist.id) },
                    showDivider = i < items.artists.lastIndex,
                    trailing = {
                        CollectionOverflow(
                            title = artist.name,
                            load = { actions.artistTracks(artist.id) },
                            onPlay = navigator.play
                        )
                    }
                )
            }

        is LibraryItems.Songs ->
            itemsIndexed(items.songs, key = { _, t -> t.id.value }) { i, track ->
                TrackRow(
                    track = track,
                    onClick = {
                        val (queue, at) = queueWindow(items.songs, i)
                        navigator.play(queue, at)
                    },
                    showDivider = i < items.songs.lastIndex
                )
            }

        // The albums are a grid.
        is LibraryItems.Albums -> Unit
    }
}

@Preview(name = "Library, light", showBackground = true, heightDp = 900)
@Preview(
    name = "Library, dark, large font",
    showBackground = true,
    heightDp = 900,
    fontScale = 1.5f,
    uiMode = android.content.res.Configuration.UI_MODE_NIGHT_YES
)
@Composable
private fun LibraryPreview() {
    UltimateTunesTheme {
        LibraryScreen(
            state = LibraryUiState(
                items = LoadState.Ready(LibraryItems.Playlists(PreviewData.playlists)),
                favouriteCount = 48
            ),
            contentPadding = PaddingValues(),
            navigator = Navigator(),
            actions = LibraryActions()
        )
    }
}
