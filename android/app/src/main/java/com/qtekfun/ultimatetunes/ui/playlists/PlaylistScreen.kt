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
import com.qtekfun.ultimatetunes.ui.actions.CollectionMenuItems
import com.qtekfun.ultimatetunes.ui.actions.OfflineNote
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

@Composable
fun PlaylistRoute(
    contentPadding: PaddingValues,
    navigator: Navigator,
    viewModel: PlaylistViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    LaunchedEffect(state.deleted) { if (state.deleted) navigator.back() }
    PlaylistScreen(
        state = state,
        contentPadding = contentPadding,
        navigator = navigator,
        actions = PlaylistActions(
            retry = viewModel::load,
            rename = viewModel::rename,
            delete = viewModel::delete,
            removeAt = viewModel::removeAt,
            messageShown = viewModel::dismissMessage,
            toggleOffline = viewModel::toggleOffline
        )
    )
}

/** What a playlist screen can do. */
data class PlaylistActions(
    val retry: () -> Unit = {},
    val rename: (String) -> Unit = {},
    val delete: () -> Unit = {},
    val removeAt: (Int) -> Unit = {},
    val messageShown: () -> Unit = {},
    val toggleOffline: () -> Unit = {}
)

private enum class PlaylistDialog { RENAME, DELETE }

/** A playlist: artwork, Play and Shuffle, its songs; rename, delete and remove songs. */
@Composable
fun PlaylistScreen(
    state: PlaylistUiState,
    contentPadding: PaddingValues,
    navigator: Navigator,
    actions: PlaylistActions
) {
    val content = (state.content as? LoadState.Ready)?.value
    var dialog by rememberSaveable { mutableStateOf<PlaylistDialog?>(null) }
    val snackbar = remember { SnackbarHostState() }
    MessageEffect(state.message, snackbar, actions.messageShown)
    LargeTitleScaffold(
        title = content?.playlist?.name.orEmpty(),
        onBack = navigator.back,
        snackbarHost = { SnackbarHost(snackbar) },
        actions = {
            if (content != null) {
                PlaylistMenu(
                    content = content,
                    isOffline = state.isOffline,
                    actions = actions,
                    onRename = { dialog = PlaylistDialog.RENAME },
                    onDelete = { dialog = PlaylistDialog.DELETE }
                )
            }
        }
    ) { inner ->
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(
                top = inner.calculateTopPadding(),
                bottom = contentPadding.calculateBottomPadding() + Dimens.SpaceXL
            )
        ) {
            when (val load = state.content) {
                LoadState.Loading -> item { LoadingState() }

                is LoadState.Failed -> item { ErrorState(load.error, actions.retry) }

                is LoadState.Ready ->
                    playlistContent(load.value, state.isOffline, navigator, actions)
            }
        }
    }
    PlaylistDialogs(dialog, content?.playlist?.name.orEmpty(), actions) { dialog = null }
}

/** The rename and delete dialogs of a playlist called [name]; [onDone] closes them. */
@Composable
private fun PlaylistDialogs(
    dialog: PlaylistDialog?,
    name: String,
    actions: PlaylistActions,
    onDone: () -> Unit
) {
    when (dialog) {
        PlaylistDialog.RENAME -> TextInputDialog(
            title = stringResource(R.string.playlist_rename),
            label = stringResource(R.string.playlist_name),
            confirmLabel = stringResource(R.string.playlist_rename),
            initial = name,
            onConfirm = {
                onDone()
                actions.rename(it)
            },
            onDismiss = onDone
        )

        PlaylistDialog.DELETE -> ConfirmDialog(
            title = stringResource(R.string.playlist_delete_title),
            message = stringResource(R.string.playlist_delete_message, name),
            confirmLabel = stringResource(R.string.playlist_delete),
            onConfirm = {
                onDone()
                actions.delete()
            },
            onDismiss = onDone
        )

        null -> Unit
    }
}

private fun LazyListScope.playlistContent(
    playlist: PlaylistContent,
    isOffline: Boolean,
    navigator: Navigator,
    actions: PlaylistActions
) {
    item { PlaylistHeader(playlist, isOffline, navigator) }
    if (playlist.tracks.isEmpty()) {
        item {
            MessageState(
                message = stringResource(R.string.playlist_empty),
                icon = R.drawable.ic_queue
            )
        }
    }
    itemsIndexed(playlist.tracks, key = { i, t -> "$i-${t.id.value}" }) { i, track ->
        TrackRow(
            track = track,
            onClick = { navigator.play(playlist.tracks, i) },
            showDivider = i < playlist.tracks.lastIndex,
            trailing = if (playlist.readonly) {
                null
            } else {
                { RemoveButton(track) { actions.removeAt(i) } }
            }
        )
    }
}

@Composable
private fun RemoveButton(track: TrackTile, onRemove: () -> Unit) {
    IconButton(onClick = onRemove) {
        Icon(
            painter = painterResource(R.drawable.ic_close),
            contentDescription = stringResource(R.string.playlist_remove_song, track.title),
            tint = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}

@Composable
private fun PlaylistMenu(
    content: PlaylistContent,
    isOffline: Boolean,
    actions: PlaylistActions,
    onRename: () -> Unit,
    onDelete: () -> Unit
) {
    var open by remember { mutableStateOf(false) }
    IconButton(onClick = { open = true }, modifier = Modifier.testTag(PLAYLIST_MENU_TAG)) {
        Icon(
            painter = painterResource(R.drawable.ic_more),
            contentDescription = stringResource(R.string.more_options),
            tint = MaterialTheme.colorScheme.primary
        )
    }
    DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
        CollectionMenuItems(
            tracks = content.tracks,
            isOffline = isOffline,
            onToggleOffline = actions.toggleOffline,
            close = { open = false }
        )
        if (!content.readonly) EditItems(onRename, onDelete, close = { open = false })
    }
}

/** Rename and delete, for the user's own playlists. */
@Composable
private fun EditItems(onRename: () -> Unit, onDelete: () -> Unit, close: () -> Unit) {
    DropdownMenuItem(
        text = { Text(stringResource(R.string.playlist_rename)) },
        leadingIcon = { Icon(painterResource(R.drawable.ic_edit), contentDescription = null) },
        onClick = {
            close()
            onRename()
        }
    )
    DropdownMenuItem(
        text = {
            Text(
                stringResource(R.string.playlist_delete),
                color = MaterialTheme.colorScheme.error
            )
        },
        leadingIcon = {
            Icon(
                painterResource(R.drawable.ic_delete),
                contentDescription = null,
                tint = MaterialTheme.colorScheme.error
            )
        },
        onClick = {
            close()
            onDelete()
        }
    )
}

@Composable
private fun PlaylistHeader(playlist: PlaylistContent, isOffline: Boolean, navigator: Navigator) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(Dimens.SpaceS)
    ) {
        Artwork(
            url = playlist.playlist.coverUrl,
            placeholderKey = playlist.playlist.id.value,
            shape = Dimens.CardShape,
            modifier = Modifier
                .widthIn(max = 280.dp)
                .fillMaxWidth(fraction = 0.66f)
                .aspectRatio(1f)
        )
        playlist.comment?.takeIf { it.isNotBlank() }?.let {
            Text(
                text = it,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(horizontal = Dimens.ScreenMargin)
            )
        }
        Text(
            text = pluralStringResource(
                R.plurals.song_count,
                playlist.playlist.songCount,
                playlist.playlist.songCount
            ),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        OfflineNote(isOffline)
        if (playlist.tracks.isNotEmpty()) {
            PlayShuffleButtons(
                onPlay = { navigator.play(playlist.tracks, 0) },
                onShuffle = { navigator.play(playlist.tracks.shuffled(), 0) }
            )
        }
    }
}

@Preview(
    name = "Playlist, dark, large font",
    showBackground = true,
    heightDp = 1100,
    fontScale = 1.4f
)
@Composable
private fun PlaylistPreview() {
    UltimateTunesTheme(darkTheme = true) {
        PlaylistScreen(
            state = PlaylistUiState(content = LoadState.Ready(PreviewData.playlist)),
            contentPadding = PaddingValues(),
            navigator = Navigator(),
            actions = PlaylistActions()
        )
    }
}
