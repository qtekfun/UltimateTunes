// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.connect

import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.size
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.DialogProperties
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.ui.theme.Dimens
import com.qtekfun.ultimatetunes.ui.theme.UltimateTunesTheme

/** Test tags of the connect-link dialog. */
const val CONNECT_LINK_DIALOG_TAG = "connectLink.dialog"
const val CONNECT_LINK_CONFIRM_TAG = "connectLink.confirm"
const val CONNECT_LINK_CANCEL_TAG = "connectLink.cancel"

/** The confirmation of a connect link, over whatever the app shows; nothing when idle. */
@Composable
fun ConnectLinkRoute(viewModel: ConnectLinkViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    ConnectLinkDialog(state = state, onConfirm = viewModel::confirm, onDismiss = viewModel::dismiss)
}

@StringRes
private fun ConnectLinkError.messageRes(): Int = when (this) {
    ConnectLinkError.MALFORMED -> R.string.connect_link_error_malformed
    ConnectLinkError.INVALID_URL -> R.string.connect_link_error_invalid_url
    ConnectLinkError.INSECURE_URL -> R.string.connect_link_error_insecure_url
    ConnectLinkError.INVALID_KEY -> R.string.connect_link_error_invalid_key
}

@Composable
fun ConnectLinkDialog(state: ConnectLinkUiState, onConfirm: () -> Unit, onDismiss: () -> Unit) {
    when (state) {
        ConnectLinkUiState.Idle -> Unit
        is ConnectLinkUiState.Refused -> RefusedDialog(state.error, onDismiss)
        is ConnectLinkUiState.Confirm -> ConfirmLinkDialog(state, onConfirm, onDismiss)
    }
}

@Composable
private fun RefusedDialog(error: ConnectLinkError, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.connect_link_refused_title)) },
        text = { Text(stringResource(error.messageRes())) },
        confirmButton = {
            TextButton(onClick = onDismiss, modifier = Modifier.testTag(CONNECT_LINK_CANCEL_TAG)) {
                Text(stringResource(R.string.close))
            }
        },
        modifier = Modifier.testTag(CONNECT_LINK_DIALOG_TAG)
    )
}

@Composable
private fun ConfirmLinkDialog(
    state: ConnectLinkUiState.Confirm,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        // No dismissing by tapping outside: the user decides with a button.
        properties = DialogProperties(dismissOnClickOutside = false),
        title = { Text(stringResource(R.string.connect_link_title, state.host)) },
        text = { ConfirmLinkText(state) },
        confirmButton = {
            TextButton(
                onClick = onConfirm,
                enabled = !state.checking,
                modifier = Modifier.testTag(CONNECT_LINK_CONFIRM_TAG)
            ) {
                if (state.checking) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(Dimens.SpaceS)
                    ) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(16.dp),
                            strokeWidth = 2.dp
                        )
                        Text(stringResource(R.string.connect_checking))
                    }
                } else {
                    Text(stringResource(R.string.connect_button))
                }
            }
        },
        dismissButton = {
            TextButton(
                onClick = onDismiss,
                enabled = !state.checking,
                modifier = Modifier.testTag(CONNECT_LINK_CANCEL_TAG)
            ) { Text(stringResource(R.string.cancel)) }
        },
        modifier = Modifier.testTag(CONNECT_LINK_DIALOG_TAG)
    )
}

@Composable
private fun ConfirmLinkText(state: ConnectLinkUiState.Confirm) {
    Column(verticalArrangement = Arrangement.spacedBy(Dimens.SpaceM)) {
        Text(stringResource(R.string.connect_link_message))
        Column {
            Text(
                text = stringResource(R.string.connect_server_url),
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Text(text = state.serverUrl, style = MaterialTheme.typography.bodyLarge)
        }
        if (state.replacing) {
            Text(
                text = stringResource(R.string.connect_link_replaces),
                style = MaterialTheme.typography.bodyMedium
            )
        }
        state.error?.let { error ->
            Text(
                text = stringResource(error.messageRes()),
                color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite }
            )
        }
    }
}

@Preview(name = "Connect link, replacing, failed")
@Composable
private fun ConnectLinkDialogPreview() {
    UltimateTunesTheme {
        ConnectLinkDialog(
            state = ConnectLinkUiState.Confirm(
                serverUrl = "https://music.example.net/",
                host = "music.example.net",
                replacing = true,
                error = ConnectError.KEY_REFUSED
            ),
            onConfirm = {},
            onDismiss = {}
        )
    }
}
