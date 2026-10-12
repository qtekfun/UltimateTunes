// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.playlists

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.ui.designsystem.Artwork
import com.qtekfun.ultimatetunes.ui.designsystem.ConfirmDialog
import com.qtekfun.ultimatetunes.ui.designsystem.ErrorState
import com.qtekfun.ultimatetunes.ui.designsystem.ItemRow
import com.qtekfun.ultimatetunes.ui.designsystem.LargeTitleScaffold
import com.qtekfun.ultimatetunes.ui.designsystem.LoadingState
import com.qtekfun.ultimatetunes.ui.designsystem.MenuRow
import com.qtekfun.ultimatetunes.ui.designsystem.MessageEffect
import com.qtekfun.ultimatetunes.ui.designsystem.MessageState
import com.qtekfun.ultimatetunes.ui.designsystem.PlayShuffleButtons
import com.qtekfun.ultimatetunes.ui.designsystem.TextInputDialog
import com.qtekfun.ultimatetunes.ui.designsystem.TrackRow
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.model.PlaylistTile
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import com.qtekfun.ultimatetunes.ui.navigation.LibraryPage
import com.qtekfun.ultimatetunes.ui.navigation.Navigator
import com.qtekfun.ultimatetunes.ui.preview.PreviewData
import com.qtekfun.ultimatetunes.ui.theme.Dimens
import com.qtekfun.ultimatetunes.ui.theme.UltimateTunesTheme

/** Test tags of the playlist screens. */
const val NEW_PLAYLIST_TAG = "playlists.new"
const val PLAYLIST_MENU_TAG = "playlist.menu"

@Composable
fun PlaylistsRoute(
    contentPadding: PaddingValues,
    navigator: Navigator,
    viewModel: PlaylistsViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    // Loaded each time the list shows, so renames and deletes made on a playlist appear.
    LaunchedEffect(Unit) { viewModel.load() }
    LaunchedEffect(state.created) {
        state.created?.let {
            viewModel.onCreatedOpened()
            navigator.openPlaylist(it)
        }
    }
    PlaylistsScreen(
        state = state,
        contentPadding = contentPadding,
        navigator = navigator,
        actions = PlaylistsActions(
            retry = viewModel::load,
            create = viewModel::create,
            messageShown = viewModel::dismissMessage
        )
    )
}

/** What the playlists list can do. */
data class PlaylistsActions(
    val retry: () -> Unit = {},
    val create: (String) -> Unit = {},
    val messageShown: () -> Unit = {}
)

/** Library › Playlists: "New Playlist", "Import Playlist" and the user's playlists. */
@Composable
fun PlaylistsScreen(
    state: PlaylistsUiState,
    contentPadding: PaddingValues,
    navigator: Navigator,
    actions: PlaylistsActions
) {
    var naming by rememberSaveable { mutableStateOf(false) }
    val snackbar = remember { SnackbarHostState() }
    MessageEffect(state.message, snackbar, actions.messageShown)
    LargeTitleScaffold(
        title = stringResource(R.string.library_playlists),
        onBack = navigator.back,
        snackbarHost = { SnackbarHost(snackbar) }
    ) { inner ->
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(
                top = inner.calculateTopPadding(),
                bottom = contentPadding.calculateBottomPadding() + Dimens.SpaceXL
            )
        ) {
            item {
                MenuRow(
                    title = stringResource(R.string.playlist_new),
                    icon = R.drawable.ic_add,
                    onClick = { naming = true },
                    modifier = Modifier.testTag(NEW_PLAYLIST_TAG)
                )
            }
            item {
                MenuRow(
                    title = stringResource(R.string.import_title),
                    icon = R.drawable.ic_upload,
                    onClick = { navigator.openPage(LibraryPage.IMPORT) }
                )
            }
            playlistRows(state.playlists, navigator, actions)
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

private fun LazyListScope.playlistRows(
    playlists: LoadState<List<PlaylistTile>>,
    navigator: Navigator,
    actions: PlaylistsActions
) {
    when (playlists) {
        LoadState.Loading -> item { LoadingState() }

        is LoadState.Failed -> item { ErrorState(playlists.error, actions.retry) }

        is LoadState.Ready -> if (playlists.value.isEmpty()) {
            item {
                MessageState(
                    message = stringResource(R.string.playlists_empty),
                    icon = R.drawable.ic_queue
                )
            }
        } else {
            itemsIndexed(playlists.value, key = { _, p -> p.id.value }) { i, playlist ->
                PlaylistRow(
                    playlist = playlist,
                    onClick = { navigator.openPlaylist(playlist.id) },
                    showDivider = i < playlists.value.lastIndex
                )
            }
        }
    }
}

@Composable
private fun PlaylistRow(playlist: PlaylistTile, onClick: () -> Unit, showDivider: Boolean) {
    ItemRow(
        title = playlist.name,
        subtitle = pluralStringResource(
            R.plurals.song_count,
            playlist.songCount,
            playlist.songCount
        ),
        artworkUrl = playlist.coverUrl,
        placeholderKey = playlist.id.value,
        isExternal = false,
        onClick = onClick,
        showDivider = showDivider
    )
}

@Preview(name = "Playlists", showBackground = true, heightDp = 900)
@Composable
private fun PlaylistsPreview() {
    UltimateTunesTheme {
        PlaylistsScreen(
            state = PlaylistsUiState(playlists = LoadState.Ready(PreviewData.playlists)),
            contentPadding = PaddingValues(),
            navigator = Navigator(),
            actions = PlaylistsActions()
        )
    }
}
