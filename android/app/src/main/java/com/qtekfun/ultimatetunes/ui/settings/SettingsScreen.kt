// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.settings

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

/** Test tags of Settings. */
const val SETTINGS_DISCONNECT_TAG = "settings.disconnect"
const val SETTINGS_OFFLINE_TAG = "settings.offline"

/** What Settings can do. */
data class SettingsActions(
    val retry: () -> Unit = {},
    val revoke: (ApiKeyId) -> Unit = {},
    val setCacheSizeMb: (Int) -> Unit = {},
    val setOfflineOnly: (Boolean) -> Unit = {},
    val setDownloadOnWifiOnly: (Boolean) -> Unit = {},
    val disconnect: () -> Unit = {},
    val messageShown: () -> Unit = {}
)

@Composable
fun SettingsRoute(
    contentPadding: PaddingValues,
    navigator: Navigator,
    viewModel: SettingsViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    SettingsScreen(
        state = state,
        contentPadding = contentPadding,
        navigator = navigator,
        actions = SettingsActions(
            retry = viewModel::load,
            revoke = viewModel::revoke,
            setCacheSizeMb = viewModel::setCacheSizeMb,
            setOfflineOnly = viewModel::setOfflineOnly,
            setDownloadOnWifiOnly = viewModel::setDownloadOnWifiOnly,
            disconnect = viewModel::disconnect,
            messageShown = viewModel::dismissMessage
        )
    )
}

/** Settings: server and account, keys per device, cache and offline, about. */
@Composable
fun SettingsScreen(
    state: SettingsUiState,
    contentPadding: PaddingValues,
    navigator: Navigator,
    actions: SettingsActions
) {
    var revoking by rememberSaveable { mutableStateOf<String?>(null) }
    var disconnecting by rememberSaveable { mutableStateOf(false) }
    val snackbar = remember { SnackbarHostState() }
    MessageEffect(state.message, snackbar, actions.messageShown)
    LargeTitleScaffold(
        title = stringResource(R.string.settings_title),
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
            server(state.server, actions, onDisconnect = { disconnecting = true })
            keys(state.keys, actions, onRevoke = { revoking = it.value })
            item { PlaybackSection(state.playback, actions) }
            item { AboutSection() }
        }
    }
    val keys = (state.keys as? LoadState.Ready)?.value
    keys?.firstOrNull { it.id.value == revoking }?.let { key ->
        ConfirmDialog(
            title = stringResource(R.string.settings_revoke_title),
            message = stringResource(R.string.settings_revoke_message, key.name),
            confirmLabel = stringResource(R.string.settings_revoke),
            onConfirm = {
                revoking = null
                actions.revoke(key.id)
            },
            onDismiss = { revoking = null }
        )
    }
    if (disconnecting) {
        ConfirmDialog(
            title = stringResource(R.string.settings_disconnect_title),
            message = stringResource(R.string.settings_disconnect_message),
            confirmLabel = stringResource(R.string.settings_disconnect),
            onConfirm = {
                disconnecting = false
                actions.disconnect()
            },
            onDismiss = { disconnecting = false }
        )
    }
}

private fun LazyListScope.server(
    server: LoadState<ServerDetails>,
    actions: SettingsActions,
    onDisconnect: () -> Unit
) {
    item { SectionHeader(stringResource(R.string.settings_server)) }
    when (server) {
        LoadState.Loading -> item { LoadingState() }

        is LoadState.Failed ->
            item { ErrorState(server.error, actions.retry) }

        is LoadState.Ready -> item {
            val details = server.value
            Column {
                Detail(stringResource(R.string.settings_address), details.address)
                details.name?.let {
                    Detail(
                        stringResource(R.string.settings_server_name),
                        listOfNotNull(it, details.version).joinToString(" ")
                    )
                }
                Detail(
                    stringResource(R.string.settings_account),
                    if (details.isAdmin) {
                        stringResource(R.string.settings_account_admin, details.username)
                    } else {
                        details.username
                    }
                )
            }
        }
    }
    item {
        OutlinedButton(
            onClick = onDisconnect,
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
}

private fun LazyListScope.keys(
    keys: LoadState<List<KeyRow>>,
    actions: SettingsActions,
    onRevoke: (ApiKeyId) -> Unit
) {
    item { SectionHeader(stringResource(R.string.settings_keys)) }
    when (keys) {
        LoadState.Loading -> item { LoadingState() }

        is LoadState.Failed ->
            item { ErrorState(keys.error, actions.retry) }

        is LoadState.Ready ->
            items(keys.value, key = { it.id.value }) { key -> KeyItem(key, onRevoke) }
    }
}

@Composable
private fun KeyItem(key: KeyRow, onRevoke: (ApiKeyId) -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = Dimens.MinRowHeight)
            .padding(horizontal = Dimens.ScreenMargin, vertical = Dimens.SpaceS),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = key.name,
                style = MaterialTheme.typography.bodyLarge,
                color = if (key.revoked) {
                    MaterialTheme.colorScheme.onSurfaceVariant
                } else {
                    MaterialTheme.colorScheme.onBackground
                }
            )
            Text(
                text = keyDetails(key),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
        when {
            key.current -> Text(
                text = stringResource(R.string.settings_key_this_device),
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.primary
            )

            key.canRevoke -> TextButton(onClick = { onRevoke(key.id) }) {
                Text(
                    stringResource(R.string.settings_revoke),
                    color = MaterialTheme.colorScheme.error
                )
            }
        }
    }
    HorizontalDivider(
        modifier = Modifier.padding(start = Dimens.ScreenMargin),
        color = MaterialTheme.colorScheme.outlineVariant
    )
}

@Composable
private fun keyDetails(key: KeyRow): String {
    val created = stringResource(R.string.settings_key_created, formatDate(key.createdAt))
    val status = when {
        key.revoked -> stringResource(R.string.settings_key_revoked)

        key.lastUsedAt != null ->
            stringResource(R.string.settings_key_last_used, formatDate(key.lastUsedAt))

        else -> stringResource(R.string.settings_key_never_used)
    }
    return "${key.prefix}… · $created · $status"
}

private fun formatDate(instant: Instant): String =
    DateTimeFormatter.ofLocalizedDate(FormatStyle.MEDIUM)
        .withZone(ZoneId.systemDefault())
        .format(instant)

@Preview(name = "Settings, light", showBackground = true, heightDp = 1600)
@Preview(
    name = "Settings, dark, large font",
    showBackground = true,
    heightDp = 1600,
    fontScale = 1.4f,
    uiMode = android.content.res.Configuration.UI_MODE_NIGHT_YES
)
@Composable
private fun SettingsPreview() {
    UltimateTunesTheme {
        SettingsScreen(
            state = PreviewData.settings,
            contentPadding = PaddingValues(),
            navigator = Navigator(),
            actions = SettingsActions()
        )
    }
}
