// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.localnet

import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.compose.LifecycleResumeEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.qtekfun.ultimatetunes.R

/** Test tags of the local network question. */
const val LOCAL_NETWORK_DIALOG_TAG = "localnetwork.dialog"
const val LOCAL_NETWORK_ALLOW_TAG = "localnetwork.allow"
const val LOCAL_NETWORK_SETTINGS_TAG = "localnetwork.settings"

/**
 * What the error screens need to know: whether the system is blocking the local network (so a
 * network error is explained, not just retried) and how to bring the explanation back.
 */
data class LocalNetworkHint(val blocked: Boolean = false, val onFix: () -> Unit = {})

val LocalLocalNetworkHint = staticCompositionLocalOf { LocalNetworkHint() }

/**
 * Explains why the local network permission is needed, asks for it, and, once it was refused,
 * opens the app's Settings page where it can still be allowed. It looks again each time the app
 * comes back to the foreground, so allowing it in Settings takes effect at once.
 */
@Composable
fun LocalNetworkAccess(viewModel: LocalNetworkViewModel, refreshKey: Any?) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    LifecycleResumeEffect(refreshKey) {
        viewModel.refresh()
        onPauseOrDispose {}
    }
    val context = LocalContext.current
    val launcher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
        viewModel::onPermissionResult
    )
    if (!state.showDialog) return
    AlertDialog(
        onDismissRequest = viewModel::dismiss,
        modifier = Modifier.testTag(LOCAL_NETWORK_DIALOG_TAG),
        title = { Text(stringResource(R.string.local_network_title)) },
        text = {
            val message = if (state.denied) {
                R.string.local_network_denied
            } else {
                R.string.local_network_rationale
            }
            Text(stringResource(message))
        },
        confirmButton = {
            if (state.denied) {
                TextButton(
                    onClick = { context.startActivity(appSettingsIntent(context.packageName)) },
                    modifier = Modifier.testTag(LOCAL_NETWORK_SETTINGS_TAG)
                ) { Text(stringResource(R.string.local_network_open_settings)) }
            } else {
                TextButton(
                    onClick = { launcher.launch(LocalNetwork.PERMISSION) },
                    modifier = Modifier.testTag(LOCAL_NETWORK_ALLOW_TAG)
                ) { Text(stringResource(R.string.local_network_allow)) }
            }
        },
        dismissButton = {
            TextButton(onClick = viewModel::dismiss) {
                Text(stringResource(R.string.local_network_not_now))
            }
        }
    )
}

/** The system's page of this app, where its permissions can be changed. */
fun appSettingsIntent(packageName: String): Intent {
    val uri = Uri.fromParts("package", packageName, null)
    return Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, uri)
        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
}
