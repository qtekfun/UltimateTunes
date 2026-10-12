// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.designsystem

import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.CompositingStrategy
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.unit.Dp

/**
 * Fades the content out over [edge] at the top and the bottom, so scrolling text dissolves into
 * what is around it instead of being cut by a hard line (the lyrics of the full player).
 */
fun Modifier.fadingEdges(edge: Dp): Modifier = this
    .graphicsLayer { compositingStrategy = CompositingStrategy.Offscreen }
    .drawWithContent {
        drawContent()
        val fade = edge.toPx().coerceAtMost(size.height / 2)
        if (fade <= 0f) return@drawWithContent
        drawRect(
            brush = Brush.verticalGradient(
                0f to Color.Transparent,
                fade / size.height to Color.Black,
                1f - fade / size.height to Color.Black,
                1f to Color.Transparent
            ),
            blendMode = BlendMode.DstIn
        )
    }
