// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.navigation

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.core.content.ContextCompat
import com.qtekfun.ultimatetunes.R

/** Test tags of the notification question. */
const val NOTIFICATIONS_DIALOG_TAG = "notifications.dialog"
const val NOTIFICATIONS_ALLOW_TAG = "notifications.allow"

/**
 * Asks once for the notification permission (Android 13+; RF-13: playback, download and export
 * progress only), after explaining what it is for. [ask] is false once answered; [onAnswered]
 * records the answer, whatever it was.
 */
@Composable
fun NotificationPermission(ask: Boolean, onAnswered: () -> Unit) {
    if (!ask || Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return
    val context = LocalContext.current
    val granted = remember(context) {
        ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) ==
            PackageManager.PERMISSION_GRANTED
    }
    val launcher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { onAnswered() }
    if (granted) {
        LaunchedEffect(Unit) { onAnswered() }
        return
    }
    AlertDialog(
        onDismissRequest = onAnswered,
        modifier = Modifier.testTag(NOTIFICATIONS_DIALOG_TAG),
        title = { Text(stringResource(R.string.notifications_title)) },
        text = { Text(stringResource(R.string.notifications_rationale)) },
        confirmButton = {
            TextButton(
                onClick = { launcher.launch(Manifest.permission.POST_NOTIFICATIONS) },
                modifier = Modifier.testTag(NOTIFICATIONS_ALLOW_TAG)
            ) { Text(stringResource(R.string.notifications_allow)) }
        },
        dismissButton = {
            TextButton(onClick = onAnswered) {
                Text(stringResource(R.string.notifications_not_now))
            }
        }
    )
}
