// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.theme

import androidx.compose.ui.graphics.Color

// The design system's palette (SPEC §5): one warm red accent on plain neutral surfaces, grouped
// surfaces one step off the background, and grey secondary text. Our own values, no Apple assets.

internal val Accent40 = Color(0xFFE0284F)
internal val Accent80 = Color(0xFFFF5C7A)
internal val OnAccentDark = Color(0xFF3D0010)

internal val SurfaceLight = Color(0xFFFFFFFF)
internal val SurfaceGroupedLight = Color(0xFFF2F2F5)
internal val SurfaceRaisedLight = Color(0xFFF7F7F9)
internal val OnSurfaceLight = Color(0xFF111114)
internal val OnSurfaceVariantLight = Color(0xFF6E6E76)
internal val OutlineLight = Color(0xFFD8D8DE)

internal val SurfaceDark = Color(0xFF000000)
internal val SurfaceGroupedDark = Color(0xFF1C1C1F)
internal val SurfaceRaisedDark = Color(0xFF141416)
internal val OnSurfaceDark = Color(0xFFF5F5F7)
internal val OnSurfaceVariantDark = Color(0xFF9A9AA2)
internal val OutlineDark = Color(0xFF38383D)

internal val ErrorLight = Color(0xFFC4162A)
internal val ErrorDark = Color(0xFFFF6B6B)

/** Placeholder artwork: a soft gradient per item until (or instead of) the real cover. */
internal val ArtworkPlaceholders = listOf(
    Color(0xFFE0284F) to Color(0xFFFF8A5C),
    Color(0xFF5B4BE0) to Color(0xFF9F7CFF),
    Color(0xFF0F8B8D) to Color(0xFF52D1B2),
    Color(0xFFDB7B12) to Color(0xFFFFC75F),
    Color(0xFF2E6BE6) to Color(0xFF6FC3FF),
    Color(0xFF7A3E9D) to Color(0xFFE07AB8)
)
