// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.designsystem

import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.runtime.staticCompositionLocalOf

/**
 * The app-wide snackbar host of the main screen, shown above the mini player and the tab bar and
 * over the full player. Null outside the main screen (previews, a screen tested alone).
 */
val LocalAppSnackbar = staticCompositionLocalOf<SnackbarHostState?> { null }

/** Where a screen shows its messages: [state] to show them, [host] for its scaffold. */
class ScreenSnackbar(val state: SnackbarHostState, val host: @Composable () -> Unit)

/**
 * The snackbar of a screen: inside the main screen, the app-wide one (a screen's own host would
 * sit at the bottom of the window, under the mini player and the tab bar); elsewhere, its own.
 */
@Composable
fun rememberScreenSnackbar(): ScreenSnackbar {
    val app = LocalAppSnackbar.current
    return remember(app) {
        if (app != null) {
            ScreenSnackbar(app) {}
        } else {
            val own = SnackbarHostState()
            ScreenSnackbar(own) { SnackbarHost(own) }
        }
    }
}
