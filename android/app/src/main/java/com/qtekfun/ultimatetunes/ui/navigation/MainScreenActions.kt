// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.navigation

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavDestination.Companion.hierarchy
import androidx.navigation.NavHostController
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.core.player.export.ExportStatus
import com.qtekfun.ultimatetunes.ui.actions.ActionEventEffect
import com.qtekfun.ultimatetunes.ui.actions.CollectionActions
import com.qtekfun.ultimatetunes.ui.actions.ExportFolderPicker
import com.qtekfun.ultimatetunes.ui.actions.ExportReportDialog
import com.qtekfun.ultimatetunes.ui.actions.LibraryActionsViewModel
import com.qtekfun.ultimatetunes.ui.actions.LocalCollectionActions
import com.qtekfun.ultimatetunes.ui.actions.LocalTrackMenu
import com.qtekfun.ultimatetunes.ui.actions.PlaylistPickerSheet
import com.qtekfun.ultimatetunes.ui.actions.TrackMenuActions
import com.qtekfun.ultimatetunes.ui.actions.TrackMenuSheet
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import com.qtekfun.ultimatetunes.ui.player.PlayerViewModel
import com.qtekfun.ultimatetunes.ui.theme.Dimens

/*
 * The app-wide song actions of the main screen (SPEC §5): the long-press menu, "Add to Playlist",
 * the export to the phone (RF-14) and what they report.
 */

/**
 * Gives [content] the song menu (opened through [onOpenMenu], with fresh favourites) and the
 * album and playlist actions of [viewModel].
 */
@Composable
internal fun ProvideLibraryActions(
    viewModel: LibraryActionsViewModel,
    onOpenMenu: (TrackTile) -> Unit,
    content: @Composable () -> Unit
) {
    val openMenu: (TrackTile) -> Unit = remember(viewModel, onOpenMenu) {
        { track ->
            viewModel.refreshFavourites()
            onOpenMenu(track)
        }
    }
    val collectionActions = remember(viewModel) {
        CollectionActions(addToPlaylist = viewModel::pickPlaylist, export = viewModel::export)
    }
    CompositionLocalProvider(
        LocalTrackMenu provides openMenu,
        LocalCollectionActions provides collectionActions,
        content = content
    )
}

/**
 * What the song menu does: queue through [player], library changes through [actions], and
 * albums, artists and stations opened in the current tab (the full player [collapse]s first).
 */
internal fun trackMenuActions(
    player: PlayerViewModel,
    actions: LibraryActionsViewModel,
    navController: NavHostController,
    collapse: () -> Unit
): TrackMenuActions {
    fun open(route: (Tab) -> String) {
        collapse()
        navController.navigate(route(currentTab(navController)))
    }
    return TrackMenuActions(
        playNext = { player.playNext(listOf(it)) },
        playLast = { player.enqueue(listOf(it)) },
        addToPlaylist = { actions.pickPlaylist(listOf(it)) },
        toggleFavourite = actions::toggleFavourite,
        toggleDownload = actions::toggleDownload,
        export = { actions.export(listOf(it)) },
        openAlbum = { id -> open { it.album(id) } },
        openArtist = { id -> open { it.artist(id) } },
        openStation = { id -> open { it.station(id) } }
    )
}

/** The tab shown now, where the song menu opens albums, artists and stations. */
private fun currentTab(navController: NavHostController): Tab {
    val destination = navController.currentDestination
    return Tab.entries.firstOrNull { tab ->
        destination?.hierarchy?.any { it.route == tab.route } == true
    } ?: Tab.LISTEN_NOW
}

/**
 * The song menu, "Add to Playlist", the export folder picker and report, and the results of those
 * actions in [snackbar].
 */
@Composable
internal fun LibraryActionsHost(
    viewModel: LibraryActionsViewModel,
    snackbar: SnackbarHostState,
    menuTrack: TrackTile?,
    onMenuDismiss: () -> Unit,
    menuActions: TrackMenuActions
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    ActionEventEffect(state.event, snackbar, viewModel::dismissEvent)
    ExportFolderPicker(state.needsFolder, viewModel::onFolderPicked)
    menuTrack?.let { track ->
        TrackMenuSheet(
            track = track,
            isFavourite = track.id in state.favourites,
            isKeptOffline = track.id in state.keptOffline,
            actions = menuActions,
            onDismiss = onMenuDismiss
        )
    }
    state.picker?.let { picker ->
        PlaylistPickerSheet(
            picker = picker,
            onPick = viewModel::addToPlaylist,
            onCreate = viewModel::createPlaylist,
            onRetry = { viewModel.pickPlaylist(picker.tracks) },
            onDismiss = viewModel::dismissPicker
        )
    }
    (state.export as? ExportStatus.Finished)?.let {
        ExportReportDialog(it.report, onDismiss = viewModel::dismissExport)
    }
}

/** "Exporting 3 of 10…" above the mini player while an export runs. */
@Composable
internal fun ExportBanner(viewModel: LibraryActionsViewModel) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val running = state.export as? ExportStatus.Running ?: return
    Text(
        text = stringResource(R.string.export_running_banner, running.done, running.total),
        style = MaterialTheme.typography.labelMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = Dimens.ScreenMargin, vertical = Dimens.SpaceXS)
            .semantics { liveRegion = LiveRegionMode.Polite }
    )
}
