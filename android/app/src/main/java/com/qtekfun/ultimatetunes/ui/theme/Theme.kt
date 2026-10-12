// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

internal val LightColors = lightColorScheme(
    primary = Accent40,
    onPrimary = Color.White,
    background = SurfaceLight,
    surface = SurfaceLight,
    onSurfaceVariant = OnSurfaceVariantLight
)

internal val DarkColors = darkColorScheme(
    primary = Accent80,
    onPrimary = OnAccentDark,
    background = SurfaceDark,
    surface = SurfaceDark,
    onSurfaceVariant = OnSurfaceVariantDark
)

/** The app's Material 3 theme, light or dark following the system. */
@Composable
fun UltimateTunesTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit
) {
    MaterialTheme(
        colorScheme = if (darkTheme) DarkColors else LightColors,
        content = content
    )
}
