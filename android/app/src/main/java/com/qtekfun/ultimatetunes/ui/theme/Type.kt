// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp

/**
 * Bold, tight headings and plain body text in the system sans-serif (no bundled or Apple fonts).
 * Every size is in `sp`, so the user's font scale applies everywhere.
 */
internal val TunesTypography: Typography = Typography().let { base ->
    val sans = FontFamily.SansSerif
    base.copy(
        // Large titles of the tabs ("Listen Now"), collapsing on scroll.
        displaySmall = TextStyle(
            fontFamily = sans,
            fontWeight = FontWeight.Bold,
            fontSize = 34.sp,
            lineHeight = 41.sp,
            letterSpacing = (-0.01).em
        ),
        // Full player title.
        headlineSmall = TextStyle(
            fontFamily = sans,
            fontWeight = FontWeight.Bold,
            fontSize = 22.sp,
            lineHeight = 28.sp
        ),
        // Section headers ("Recently Played").
        titleLarge = TextStyle(
            fontFamily = sans,
            fontWeight = FontWeight.Bold,
            fontSize = 22.sp,
            lineHeight = 28.sp,
            letterSpacing = (-0.005).em
        ),
        // Collapsed top bar title.
        titleMedium = TextStyle(
            fontFamily = sans,
            fontWeight = FontWeight.SemiBold,
            fontSize = 17.sp,
            lineHeight = 22.sp
        ),
        // Card and row titles.
        titleSmall = TextStyle(
            fontFamily = sans,
            fontWeight = FontWeight.Medium,
            fontSize = 15.sp,
            lineHeight = 20.sp
        ),
        bodyLarge = TextStyle(
            fontFamily = sans,
            fontWeight = FontWeight.Normal,
            fontSize = 17.sp,
            lineHeight = 22.sp
        ),
        bodyMedium = TextStyle(
            fontFamily = sans,
            fontWeight = FontWeight.Normal,
            fontSize = 15.sp,
            lineHeight = 20.sp
        ),
        bodySmall = TextStyle(
            fontFamily = sans,
            fontWeight = FontWeight.Normal,
            fontSize = 13.sp,
            lineHeight = 18.sp
        ),
        labelSmall = TextStyle(
            fontFamily = sans,
            fontWeight = FontWeight.Medium,
            fontSize = 11.sp,
            lineHeight = 13.sp,
            letterSpacing = 0.02.em
        )
    )
}
