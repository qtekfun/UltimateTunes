// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.settings

import android.text.format.DateUtils
import android.text.format.Formatter
import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
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
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.core.api.model.ApiKeyId
import com.qtekfun.ultimatetunes.ui.designsystem.ConfirmDialog
import com.qtekfun.ultimatetunes.ui.designsystem.ErrorState
import com.qtekfun.ultimatetunes.ui.designsystem.LoadingState
import com.qtekfun.ultimatetunes.ui.designsystem.MenuRow
import com.qtekfun.ultimatetunes.ui.designsystem.MessageEffect
import com.qtekfun.ultimatetunes.ui.designsystem.ScreenScaffold
import com.qtekfun.ultimatetunes.ui.designsystem.SectionHeader
import com.qtekfun.ultimatetunes.ui.designsystem.messageRes
import com.qtekfun.ultimatetunes.ui.designsystem.rememberScreenSnackbar
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.navigation.LibraryPage
import com.qtekfun.ultimatetunes.ui.navigation.Navigator
import com.qtekfun.ultimatetunes.ui.preview.PreviewData
import com.qtekfun.ultimatetunes.ui.theme.Dimens
import com.qtekfun.ultimatetunes.ui.theme.UltimateTunesTheme
import com.qtekfun.ultimatetunes.ui.youtube.YoutubeAccountSection
import com.qtekfun.ultimatetunes.ui.youtube.YoutubeAccountUiState
import com.qtekfun.ultimatetunes.ui.youtube.YoutubeAccountViewModel
import com.qtekfun.ultimatetunes.ui.youtube.YoutubeActions
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle

/** Who is connected to which server, and whether it can be reached now. */
@Composable
internal fun ConnectionCard(state: SettingsUiState) {
    val details = (state.server as? LoadState.Ready)?.value
    val status = stringResource(
        when {
            !state.online -> R.string.settings_status_offline
            state.playback.offlineOnly -> R.string.settings_status_offline_mode
            state.server is LoadState.Failed -> R.string.settings_status_unreachable
            else -> R.string.settings_status_connected
        }
    )
    Card(Modifier.testTag(SETTINGS_CONNECTION_TAG)) {
        Text(
            text = details?.username ?: stringResource(R.string.settings_account),
            style = MaterialTheme.typography.titleSmall
        )
        Text(
            text = stringResource(
                R.string.settings_connection,
                details?.address ?: state.address,
                status
            ),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite }
        )
    }
}

/** The space the music takes on the phone, the state of the sync and "Sync now". */
@Composable
internal fun StorageCard(state: SettingsUiState, onSyncNow: () -> Unit) {
    val context = LocalContext.current
    Card {
        Text(
            text = stringResource(
                R.string.settings_on_phone,
                Formatter.formatShortFileSize(context, state.usedBytes ?: 0)
            ),
            style = MaterialTheme.typography.titleSmall
        )
        val downloaded = pluralStringResource(
            R.plurals.settings_downloaded_songs,
            state.downloadedCount,
            state.downloadedCount
        )
        val lastSync = state.lastSync
        val synced = when {
            state.syncing -> stringResource(R.string.settings_syncing)

            lastSync == null -> stringResource(R.string.settings_never_synced)

            else -> stringResource(
                R.string.settings_synced,
                DateUtils.getRelativeTimeSpanString(
                    lastSync.toEpochMilli(),
                    System.currentTimeMillis(),
                    DateUtils.MINUTE_IN_MILLIS
                ).toString()
            )
        }
        Text(
            text = "$downloaded · $synced",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        state.syncError?.let {
            Text(
                text = stringResource(it.messageRes()),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error
            )
        }
        Button(
            onClick = onSyncNow,
            shape = Dimens.PillShape,
            modifier = Modifier.heightIn(min = 48.dp).testTag(SETTINGS_SYNC_NOW_TAG)
        ) { Text(stringResource(R.string.settings_sync_now)) }
    }
}

@Composable
private fun Card(modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    Surface(
        shape = Dimens.CardShape,
        color = MaterialTheme.colorScheme.surfaceContainer,
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = Dimens.ScreenMargin, vertical = Dimens.SpaceXS)
    ) {
        Column(
            modifier = Modifier.padding(Dimens.SpaceL),
            verticalArrangement = Arrangement.spacedBy(Dimens.SpaceXS)
        ) { content() }
    }
}

@Composable
internal fun DisconnectButton(onClick: () -> Unit) {
    OutlinedButton(
        onClick = onClick,
        shape = Dimens.PillShape,
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = Dimens.ScreenMargin, vertical = Dimens.SpaceM)
            .heightIn(min = 48.dp)
            .testTag(SETTINGS_DISCONNECT_TAG)
    ) {
        Text(
            stringResource(R.string.settings_disconnect),
            color = MaterialTheme.colorScheme.error
        )
    }
}

/** The questions before revoking a key and before disconnecting; [onDone] closes them. */
@Composable
internal fun SettingsDialogs(
    keys: List<KeyRow>,
    revoking: String?,
    disconnecting: Boolean,
    actions: SettingsActions,
    onDone: () -> Unit
) {
    keys.firstOrNull { it.id.value == revoking }?.let { key ->
        ConfirmDialog(
            title = stringResource(R.string.settings_revoke_title),
            message = stringResource(R.string.settings_revoke_message, key.name),
            confirmLabel = stringResource(R.string.settings_revoke),
            onConfirm = {
                onDone()
                actions.revoke(key.id)
            },
            onDismiss = onDone
        )
    }
    if (disconnecting) {
        ConfirmDialog(
            title = stringResource(R.string.settings_disconnect_title),
            message = stringResource(R.string.settings_disconnect_message),
            confirmLabel = stringResource(R.string.settings_disconnect),
            onConfirm = {
                onDone()
                actions.disconnect()
            },
            onDismiss = onDone
        )
    }
}
