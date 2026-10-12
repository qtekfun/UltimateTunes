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
    secondary = Accent40,
    onSecondary = Color.White,
    background = SurfaceLight,
    onBackground = OnSurfaceLight,
    surface = SurfaceLight,
    onSurface = OnSurfaceLight,
    surfaceVariant = SurfaceGroupedLight,
    onSurfaceVariant = OnSurfaceVariantLight,
    surfaceContainer = SurfaceRaisedLight,
    surfaceContainerHigh = SurfaceGroupedLight,
    surfaceContainerHighest = SurfaceGroupedLight,
    surfaceContainerLow = SurfaceRaisedLight,
    outline = OutlineLight,
    outlineVariant = OutlineLight,
    error = ErrorLight
)

internal val DarkColors = darkColorScheme(
    primary = Accent80,
    onPrimary = OnAccentDark,
    secondary = Accent80,
    onSecondary = OnAccentDark,
    background = SurfaceDark,
    onBackground = OnSurfaceDark,
    surface = SurfaceDark,
    onSurface = OnSurfaceDark,
    surfaceVariant = SurfaceGroupedDark,
    onSurfaceVariant = OnSurfaceVariantDark,
    surfaceContainer = SurfaceRaisedDark,
    surfaceContainerHigh = SurfaceGroupedDark,
    surfaceContainerHighest = SurfaceGroupedDark,
    surfaceContainerLow = SurfaceRaisedDark,
    outline = OutlineDark,
    outlineVariant = OutlineDark,
    error = ErrorDark
)

/**
 * The app's theme (SPEC §5): Material 3 adapted to an Apple Music-inspired look, light or dark
 * following the system. No dynamic colour: the accent is part of the identity.
 */
@Composable
fun UltimateTunesTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit
) {
    MaterialTheme(
        colorScheme = if (darkTheme) DarkColors else LightColors,
        typography = TunesTypography,
        content = content
    )
}
