// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.settings

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.selection.toggleable
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.RadioButton
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.core.net.toUri
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.core.api.model.ApiKeyId
import com.qtekfun.ultimatetunes.ui.designsystem.ConfirmDialog
import com.qtekfun.ultimatetunes.ui.designsystem.ErrorState
import com.qtekfun.ultimatetunes.ui.designsystem.LargeTitleScaffold
import com.qtekfun.ultimatetunes.ui.designsystem.LoadingState
import com.qtekfun.ultimatetunes.ui.designsystem.MessageEffect
import com.qtekfun.ultimatetunes.ui.designsystem.SectionHeader
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.navigation.Navigator
import com.qtekfun.ultimatetunes.ui.preview.PreviewData
import com.qtekfun.ultimatetunes.ui.theme.Dimens
import com.qtekfun.ultimatetunes.ui.theme.UltimateTunesTheme
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle

private const val MB_PER_GB = 1024

@Composable
internal fun PlaybackSection(playback: PlaybackSettings, actions: SettingsActions) {
    Column {
        SectionHeader(stringResource(R.string.settings_playback))
        Text(
            text = stringResource(R.string.settings_cache_size),
            style = MaterialTheme.typography.titleSmall,
            modifier = Modifier.padding(horizontal = Dimens.ScreenMargin)
        )
        Text(
            text = stringResource(R.string.settings_cache_help),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = Dimens.ScreenMargin)
        )
        Column(modifier = Modifier.selectableGroup()) {
            PlaybackSettings.CACHE_SIZES_MB.forEach { mb ->
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(min = 48.dp)
                        .selectable(
                            selected = playback.cacheSizeMb == mb,
                            onClick = { actions.setCacheSizeMb(mb) },
                            role = Role.RadioButton
                        )
                        .padding(horizontal = Dimens.ScreenMargin),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    RadioButton(selected = playback.cacheSizeMb == mb, onClick = null)
                    Text(
                        text = cacheLabel(mb),
                        style = MaterialTheme.typography.bodyLarge,
                        modifier = Modifier.padding(start = Dimens.SpaceM)
                    )
                }
            }
        }
        SwitchRow(
            title = stringResource(R.string.settings_offline_only),
            subtitle = stringResource(R.string.settings_offline_only_help),
            checked = playback.offlineOnly,
            onChange = actions.setOfflineOnly,
            modifier = Modifier.testTag(SETTINGS_OFFLINE_TAG)
        )
        SwitchRow(
            title = stringResource(R.string.settings_wifi_only),
            subtitle = stringResource(R.string.settings_wifi_only_help),
            checked = playback.downloadOnWifiOnly,
            onChange = actions.setDownloadOnWifiOnly
        )
        Text(
            text = stringResource(R.string.settings_quality_info),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = Dimens.ScreenMargin, vertical = Dimens.SpaceS)
        )
    }
}

@Composable
private fun cacheLabel(mb: Int): String = if (mb >= MB_PER_GB) {
    stringResource(R.string.size_gb, mb / MB_PER_GB)
} else {
    stringResource(R.string.size_mb, mb)
}

@Composable
private fun SwitchRow(
    title: String,
    subtitle: String,
    checked: Boolean,
    onChange: (Boolean) -> Unit,
    modifier: Modifier = Modifier
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .heightIn(min = Dimens.MinRowHeight)
            .toggleable(value = checked, onValueChange = onChange, role = Role.Switch)
            .padding(horizontal = Dimens.ScreenMargin, vertical = Dimens.SpaceS),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column(modifier = Modifier.weight(1f).padding(end = Dimens.SpaceM)) {
            Text(text = title, style = MaterialTheme.typography.bodyLarge)
            Text(
                text = subtitle,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
        Switch(checked = checked, onCheckedChange = null)
    }
}

/** Test tag of the export folder button. */
const val SETTINGS_EXPORT_FOLDER_TAG = "settings.exportFolder"

/** The export folder (RF-14): its name, and a button opening the system folder picker. */
@Composable
internal fun ExportSection(folder: String?, onPicked: (String?) -> Unit) {
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocumentTree()) {
        onPicked(it?.toString())
    }
    Column {
        SectionHeader(stringResource(R.string.settings_export))
        Text(
            text = stringResource(R.string.settings_export_help),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = Dimens.ScreenMargin)
        )
        Detail(
            stringResource(R.string.settings_export_folder),
            folder?.let(::folderName) ?: stringResource(R.string.settings_export_folder_none)
        )
        TextButton(
            onClick = { launcher.launch(folder?.toUri()) },
            modifier = Modifier
                .padding(horizontal = Dimens.SpaceS)
                .testTag(SETTINGS_EXPORT_FOLDER_TAG)
        ) { Text(stringResource(R.string.settings_export_folder_change)) }
    }
}

/** "Music/Exports" for a tree URI like `content://…/tree/primary%3AMusic%2FExports`. */
internal fun folderName(uri: String): String {
    val document = uri.toUri().lastPathSegment ?: return uri
    return document.substringAfter(':', document).ifEmpty { document }
}

@Composable
internal fun AboutSection() {
    val context = LocalContext.current
    val version = remember(context) {
        runCatching {
            context.packageManager.getPackageInfo(context.packageName, 0).versionName
        }.getOrNull().orEmpty()
    }
    Column {
        SectionHeader(stringResource(R.string.settings_about))
        Detail(
            stringResource(R.string.app_name),
            stringResource(R.string.settings_version, version)
        )
        Text(
            text = stringResource(R.string.settings_license),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = Dimens.ScreenMargin, vertical = Dimens.SpaceS)
        )
    }
}

@Composable
internal fun Detail(label: String, value: String) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = Dimens.ScreenMargin, vertical = Dimens.SpaceS)
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Text(text = value, style = MaterialTheme.typography.bodyLarge)
    }
}
