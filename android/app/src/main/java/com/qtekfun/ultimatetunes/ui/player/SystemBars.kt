// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.player

import androidx.activity.compose.LocalActivity
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat

/** The player is dark in both themes: while [shown], the status bar icons are light. */
@Composable
internal fun LightStatusBarIcons(shown: Boolean) {
    val view = LocalView.current
    val window = LocalActivity.current?.window ?: return
    DisposableEffect(window, shown) {
        val insets = WindowCompat.getInsetsController(window, view)
        val before = insets.isAppearanceLightStatusBars
        if (shown) insets.isAppearanceLightStatusBars = false
        onDispose { insets.isAppearanceLightStatusBars = before }
    }
}
