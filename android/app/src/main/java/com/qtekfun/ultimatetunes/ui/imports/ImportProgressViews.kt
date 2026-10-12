// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.imports

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.core.api.model.ImportFileFormat
import com.qtekfun.ultimatetunes.core.api.model.ImportId
import com.qtekfun.ultimatetunes.core.api.model.ImportItemState
import com.qtekfun.ultimatetunes.core.api.model.ImportSource
import com.qtekfun.ultimatetunes.core.api.model.ImportState
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import com.qtekfun.ultimatetunes.ui.designsystem.ErrorState
import com.qtekfun.ultimatetunes.ui.designsystem.ItemRow
import com.qtekfun.ultimatetunes.ui.designsystem.LargeTitleScaffold
import com.qtekfun.ultimatetunes.ui.designsystem.LoadingState
import com.qtekfun.ultimatetunes.ui.designsystem.SectionHeader
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.navigation.Navigator
import com.qtekfun.ultimatetunes.ui.theme.Dimens
import com.qtekfun.ultimatetunes.ui.theme.UltimateTunesTheme
import kotlinx.coroutines.launch

internal fun LazyListScope.progress(
    current: ImportProgress,
    navigator: Navigator,
    actions: ImportActions
) {
    item { ProgressCard(current, navigator, actions) }
    if (current.rows.isNotEmpty()) {
        item { SectionHeader(stringResource(R.string.import_report)) }
        items(current.rows, key = { "row-${it.position}" }) { row -> ReportRow(row, navigator) }
    }
}

@Composable
private fun ProgressCard(current: ImportProgress, navigator: Navigator, actions: ImportActions) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = Dimens.ScreenMargin, vertical = Dimens.SpaceM)
            .testTag(IMPORT_PROGRESS_TAG),
        shape = Dimens.CardShape
    ) {
        Column(
            modifier = Modifier.padding(Dimens.SpaceL),
            verticalArrangement = Arrangement.spacedBy(Dimens.SpaceS)
        ) {
            Text(
                text = current.name ?: stringResource(R.string.import_untitled),
                style = MaterialTheme.typography.titleMedium
            )
            Text(
                text = stringResource(current.state.labelRes()),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite }
            )
            if (current.inProgress) {
                LinearProgressIndicator(
                    progress = { current.progress.toFloat().coerceIn(0f, 1f) },
                    modifier = Modifier.fillMaxWidth()
                )
            }
            if (current.total > 0) {
                Text(
                    text = stringResource(
                        R.string.import_counts,
                        current.matched,
                        current.total,
                        current.notFound
                    ),
                    style = MaterialTheme.typography.bodySmall
                )
            }
            Row(horizontalArrangement = Arrangement.spacedBy(Dimens.SpaceS)) {
                current.playlistId?.takeIf { !current.inProgress }?.let { id: PlaylistId ->
                    Button(onClick = { navigator.openPlaylist(id) }, shape = Dimens.PillShape) {
                        Text(stringResource(R.string.import_open_playlist))
                    }
                }
                TextButton(onClick = actions.closeCurrent) { Text(stringResource(R.string.close)) }
            }
        }
    }
}

@Composable
private fun ReportRow(row: ImportRow, navigator: Navigator) {
    val match = row.match
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = Dimens.MinRowHeight)
            .semantics(mergeDescendants = true) {}
            .padding(horizontal = Dimens.ScreenMargin, vertical = Dimens.SpaceS),
        verticalAlignment = Alignment.CenterVertically
    ) {
        val matched = row.state == ImportItemState.MATCHED
        Icon(
            painter = painterResource(
                if (matched) R.drawable.ic_check_circle else R.drawable.ic_error
            ),
            contentDescription = stringResource(row.state.labelRes()),
            tint = if (matched) {
                MaterialTheme.colorScheme.primary
            } else {
                MaterialTheme.colorScheme.error
            },
            modifier = Modifier.size(24.dp)
        )
        Column(modifier = Modifier.weight(1f).padding(start = Dimens.SpaceM)) {
            Text(text = row.title, style = MaterialTheme.typography.bodyLarge)
            val detail = if (match != null) {
                stringResource(R.string.import_matched_as, match.title, match.artist)
            } else {
                row.artist
            }
            detail?.let {
                Text(
                    text = it,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
        match?.albumId?.let { albumId ->
            TextButton(onClick = { navigator.openAlbum(albumId) }) {
                Text(stringResource(R.string.go_to_album))
            }
        }
    }
}
