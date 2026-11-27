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
import androidx.compose.foundation.lazy.grid.GridItemSpan
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
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import com.qtekfun.ultimatetunes.ui.navigation.LibraryPage
import com.qtekfun.ultimatetunes.ui.navigation.Navigator
import com.qtekfun.ultimatetunes.ui.preview.PreviewData
import com.qtekfun.ultimatetunes.ui.theme.Dimens
import com.qtekfun.ultimatetunes.ui.theme.UltimateTunesTheme

@Composable
internal fun PlaylistRow(
    playlist: PlaylistTile,
    isOffline: Boolean,
    showDivider: Boolean,
    navigator: Navigator,
    actions: LibraryActions
) {
    ItemRow(
        title = playlist.name,
        subtitle = pluralStringResource(
            R.plurals.song_count,
            playlist.songCount,
            playlist.songCount
        ),
        artworkUrl = playlist.coverUrl,
        placeholderKey = playlist.id.value,
        onClick = { navigator.openPlaylist(playlist.id) },
        showDivider = showDivider,
        available = LocalAvailability.current.canPlayPlaylist(playlist.id),
        trailing = {
            CollectionOverflow(
                title = playlist.name,
                load = { actions.playlistTracks(playlist.id) },
                onPlay = navigator.play,
                isOffline = isOffline,
                onToggleOffline = { actions.toggleOffline(playlist) }
            )
        }
    )
}

/** "New playlist or import", which offers both. */
@Composable
internal fun NewOrImport(navigator: Navigator, onNewPlaylist: () -> Unit) {
    var open by remember { mutableStateOf(false) }
    Box {
        MenuRow(
            title = stringResource(R.string.library_new_or_import),
            icon = R.drawable.ic_add,
            onClick = { open = true },
            modifier = Modifier.testTag(LIBRARY_NEW_TAG)
        )
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            DropdownMenuItem(
                text = { Text(stringResource(R.string.playlist_new)) },
                leadingIcon = {
                    Icon(painterResource(R.drawable.ic_add), contentDescription = null)
                },
                onClick = {
                    open = false
                    onNewPlaylist()
                },
                modifier = Modifier.testTag(NEW_PLAYLIST_TAG)
            )
            DropdownMenuItem(
                text = { Text(stringResource(R.string.import_title)) },
                leadingIcon = {
                    Icon(painterResource(R.drawable.ic_upload), contentDescription = null)
                },
                onClick = {
                    open = false
                    navigator.openPage(LibraryPage.IMPORT)
                },
                modifier = Modifier.testTag(LIBRARY_IMPORT_TAG)
            )
        }
    }
}

@Composable
internal fun CollectionRows(state: LibraryUiState, navigator: Navigator) {
    Column {
        MenuRow(
            title = stringResource(R.string.library_favourites),
            icon = R.drawable.ic_favorite,
            subtitle = pluralStringResource(
                R.plurals.song_count,
                state.favouriteCount,
                state.favouriteCount
            ),
            onClick = { navigator.openPage(LibraryPage.FAVOURITES) },
            modifier = Modifier.testTag(libraryRowTag(LibraryPage.FAVOURITES))
        )
        MenuRow(
            title = stringResource(R.string.library_downloads),
            icon = R.drawable.ic_download,
            subtitle = pluralStringResource(
                R.plurals.song_count,
                state.downloadCount,
                state.downloadCount
            ),
            onClick = { navigator.openPage(LibraryPage.DOWNLOADS) },
            modifier = Modifier.testTag(libraryRowTag(LibraryPage.DOWNLOADS))
        )
    }
}

@Composable
internal fun EmptyList(filter: LibraryFilter, onPhoneOnly: Boolean) {
    val message = when {
        onPhoneOnly -> R.string.library_nothing_on_phone
        filter == LibraryFilter.PLAYLISTS -> R.string.playlists_empty
        else -> R.string.library_empty
    }
    MessageState(message = stringResource(message), icon = R.drawable.ic_library)
}
