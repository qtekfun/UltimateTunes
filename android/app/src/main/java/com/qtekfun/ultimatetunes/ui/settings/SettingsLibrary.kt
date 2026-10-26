// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.settings

import android.text.format.Formatter
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.ui.theme.Dimens

/** Test tags of the whole-library-offline rows. */
const val SETTINGS_LIBRARY_OFFLINE_TAG = "settings.libraryOffline"
const val SETTINGS_LIBRARY_STATUS_TAG = "settings.libraryStatus"

/** "Keep my whole library offline" (RF-12): the switch, its limit and what fits. */
@Composable
internal fun LibraryOfflineSection(state: SettingsUiState, actions: SettingsActions) {
    val playback = state.playback
    SwitchRow(
        title = stringResource(R.string.settings_library_offline),
        subtitle = stringResource(R.string.settings_library_offline_help),
        checked = playback.libraryOffline,
        onChange = actions.setLibraryOffline,
        modifier = Modifier.testTag(SETTINGS_LIBRARY_OFFLINE_TAG)
    )
    SizeChoices(
        title = stringResource(R.string.settings_library_limit),
        help = stringResource(R.string.settings_library_limit_help),
        sizesMb = PlaybackSettings.LIBRARY_OFFLINE_LIMITS_MB,
        selectedMb = playback.libraryOfflineLimitMb,
        onSelect = actions.setLibraryOfflineLimitMb
    )
    LibraryOfflineStatus(state)
}

@Composable
private fun LibraryOfflineStatus(state: SettingsUiState) {
    val kept = state.libraryKept
    // Once the setting has synced, what it did; before, what the limit would do.
    val synced = kept?.report
    val report = synced ?: state.libraryPreview
    val lines = buildList {
        if (report != null) {
            val total = countAndSize(report.totalCount, report.totalBytes)
            add(
                stringResource(
                    if (report.estimated) {
                        R.string.settings_library_size_estimated
                    } else {
                        R.string.settings_library_size
                    },
                    total.first,
                    total.second
                )
            )
            if (synced != null) {
                val onPhone = countAndSize(report.keptCount, report.keptBytes)
                add(stringResource(R.string.settings_library_kept, onPhone.first, onPhone.second))
            }
            if (report.leftOutCount > 0) {
                val out = countAndSize(report.leftOutCount, report.leftOutBytes)
                add(
                    stringResource(
                        if (synced != null) {
                            R.string.settings_library_left_out
                        } else {
                            R.string.settings_library_would_not_fit
                        },
                        out.first,
                        out.second
                    )
                )
            }
        } else if (kept != null) {
            add(stringResource(R.string.settings_library_waiting))
        }
    }
    if (lines.isEmpty()) return
    Column(
        modifier = Modifier
            .padding(horizontal = Dimens.ScreenMargin, vertical = Dimens.SpaceS)
            .semantics { liveRegion = LiveRegionMode.Polite }
            .testTag(SETTINGS_LIBRARY_STATUS_TAG)
    ) {
        lines.forEach { line ->
            Text(
                text = line,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

/** "1,234 songs" and "8.2 GB". */
@Composable
private fun countAndSize(count: Int, bytes: Long): Pair<String, String> =
    pluralStringResource(R.plurals.song_count, count, count) to
        Formatter.formatShortFileSize(LocalContext.current, bytes)

/** A titled group of radio rows, one per size in MB. */
@Composable
internal fun SizeChoices(
    title: String,
    help: String,
    sizesMb: List<Int>,
    selectedMb: Int,
    onSelect: (Int) -> Unit
) {
    Text(
        text = title,
        style = MaterialTheme.typography.titleSmall,
        modifier = Modifier.padding(horizontal = Dimens.ScreenMargin)
    )
    Text(
        text = help,
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.padding(horizontal = Dimens.ScreenMargin)
    )
    Column(modifier = Modifier.selectableGroup()) {
        sizesMb.forEach { mb ->
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = 48.dp)
                    .selectable(
                        selected = selectedMb == mb,
                        onClick = { onSelect(mb) },
                        role = Role.RadioButton
                    )
                    .padding(horizontal = Dimens.ScreenMargin),
                verticalAlignment = Alignment.CenterVertically
            ) {
                RadioButton(selected = selectedMb == mb, onClick = null)
                Text(
                    text = cacheLabel(mb),
                    style = MaterialTheme.typography.bodyLarge,
                    modifier = Modifier.padding(start = Dimens.SpaceM)
                )
            }
        }
    }
}
