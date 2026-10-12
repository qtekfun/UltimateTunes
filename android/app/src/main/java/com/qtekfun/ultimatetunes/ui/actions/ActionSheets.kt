// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.actions

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.core.player.export.ExportReport
import com.qtekfun.ultimatetunes.core.player.export.SkipReason
import com.qtekfun.ultimatetunes.ui.designsystem.ErrorState
import com.qtekfun.ultimatetunes.ui.designsystem.ItemRow
import com.qtekfun.ultimatetunes.ui.designsystem.LoadingState
import com.qtekfun.ultimatetunes.ui.designsystem.MenuRow
import com.qtekfun.ultimatetunes.ui.designsystem.TextInputDialog
import com.qtekfun.ultimatetunes.ui.designsystem.messageRes
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.model.PlaylistTile
import com.qtekfun.ultimatetunes.ui.theme.Dimens

/** Test tags of "Add to Playlist" and the export report. */
const val PLAYLIST_PICKER_TAG = "picker.playlists"
const val PLAYLIST_PICKER_NEW_TAG = "picker.new"
const val EXPORT_REPORT_TAG = "export.report"

/** "Add to Playlist": a new playlist, or one of the user's. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PlaylistPickerSheet(
    picker: PlaylistPicker,
    onPick: (PlaylistTile) -> Unit,
    onCreate: (String) -> Unit,
    onRetry: () -> Unit,
    onDismiss: () -> Unit
) {
    var naming by rememberSaveable { mutableStateOf(false) }
    val sheet = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = sheet,
        modifier = Modifier.testTag(PLAYLIST_PICKER_TAG)
    ) {
        Text(
            text = stringResource(R.string.picker_title),
            style = MaterialTheme.typography.titleLarge,
            modifier = Modifier
                .padding(horizontal = Dimens.ScreenMargin, vertical = Dimens.SpaceS)
                .semantics { heading() }
        )
        MenuRow(
            title = stringResource(R.string.picker_new),
            icon = R.drawable.ic_add,
            onClick = { naming = true },
            modifier = Modifier.testTag(PLAYLIST_PICKER_NEW_TAG)
        )
        PickerPlaylists(picker.playlists, onPick, onRetry)
        Spacer(Modifier.height(Dimens.SpaceXL))
    }
    if (naming) {
        TextInputDialog(
            title = stringResource(R.string.playlist_new),
            label = stringResource(R.string.playlist_name),
            confirmLabel = stringResource(R.string.picker_title),
            onConfirm = {
                naming = false
                onCreate(it)
            },
            onDismiss = { naming = false }
        )
    }
}

/** Rows of playlists shown before the list scrolls. */
private const val PICKER_VISIBLE_ROWS = 7
private val PICKER_LIST_MAX = Dimens.MinRowHeight * PICKER_VISIBLE_ROWS

/** The user's playlists to pick from. */
@Composable
private fun PickerPlaylists(
    playlists: LoadState<List<PlaylistTile>>,
    onPick: (PlaylistTile) -> Unit,
    onRetry: () -> Unit
) {
    when (playlists) {
        LoadState.Loading -> LoadingState()

        is LoadState.Failed -> ErrorState(playlists.error, onRetry)

        is LoadState.Ready -> if (playlists.value.isEmpty()) {
            Text(
                text = stringResource(R.string.picker_empty),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(Dimens.ScreenMargin)
            )
        } else {
            LazyColumn(modifier = Modifier.heightIn(max = PICKER_LIST_MAX)) {
                items(playlists.value, key = { it.id.value }) { playlist ->
                    ItemRow(
                        title = playlist.name,
                        subtitle = pluralStringResource(
                            R.plurals.song_count,
                            playlist.songCount,
                            playlist.songCount
                        ),
                        artworkUrl = playlist.coverUrl,
                        placeholderKey = playlist.id.value,
                        onClick = { onPick(playlist) }
                    )
                }
            }
        }
    }
}

/** What an export did: songs copied, and the ones skipped with why (RF-14). */
@Composable
fun ExportReportDialog(report: ExportReport, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        modifier = Modifier.testTag(EXPORT_REPORT_TAG),
        title = { Text(stringResource(R.string.export_report_title)) },
        text = {
            Column(modifier = Modifier.verticalScroll(rememberScrollState())) {
                Text(
                    pluralStringResource(
                        R.plurals.export_report_copied,
                        report.exported,
                        report.exported
                    )
                )
                if (report.skipped.isNotEmpty()) {
                    Text(
                        text = stringResource(R.string.export_report_skipped),
                        style = MaterialTheme.typography.titleSmall,
                        modifier = Modifier.padding(top = Dimens.SpaceM)
                    )
                    report.skipped.forEach { skipped ->
                        Text(
                            text = stringResource(
                                R.string.export_skipped_item,
                                skipped.track.title,
                                stringResource(skipped.reason.labelRes())
                            ),
                            style = MaterialTheme.typography.bodySmall
                        )
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.ok)) } }
    )
}

private fun SkipReason.labelRes(): Int = when (this) {
    SkipReason.NOT_IN_LIBRARY -> R.string.export_skip_not_in_library
    SkipReason.NOT_ON_PHONE -> R.string.export_skip_not_on_phone
    SkipReason.UNKNOWN_FORMAT -> R.string.export_skip_unknown_format
    SkipReason.ALREADY_IN_FOLDER -> R.string.export_skip_already_in_folder
    SkipReason.WRITE_FAILED -> R.string.export_skip_write_failed
}

/**
 * Opens the system folder picker (Storage Access Framework) when an export needs a folder, and
 * hands the result to [onPicked] (null when cancelled).
 */
@Composable
fun ExportFolderPicker(needsFolder: Boolean, onPicked: (String?) -> Unit) {
    var launched by rememberSaveable { mutableStateOf(false) }
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocumentTree()) {
        launched = false
        onPicked(it?.toString())
    }
    LaunchedEffect(needsFolder) {
        if (needsFolder && !launched) {
            launched = true
            launcher.launch(null)
        }
    }
}

/** Shows the result of the last action once, in [host]. */
@Composable
fun ActionEventEffect(event: ActionEvent?, host: SnackbarHostState, onShown: () -> Unit) {
    val message = when (event) {
        null -> null

        is ActionEvent.AddedToPlaylist -> pluralStringResource(
            R.plurals.event_added_to_playlist,
            event.count,
            event.count,
            event.playlist
        )

        ActionEvent.Downloading -> stringResource(R.string.event_downloading)

        ActionEvent.DownloadRemoved -> stringResource(R.string.event_download_removed)

        is ActionEvent.FavouriteChanged -> stringResource(
            if (event.added) R.string.event_favourite_added else R.string.event_favourite_removed
        )

        is ActionEvent.ExportStarted ->
            pluralStringResource(R.plurals.event_export_started, event.count, event.count)

        ActionEvent.ExportBusy -> stringResource(R.string.event_export_busy)

        is ActionEvent.Failed -> stringResource(event.error.messageRes())
    }
    LaunchedEffect(event) {
        if (message != null) {
            host.showSnackbar(message)
            onShown()
        }
    }
}
