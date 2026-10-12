// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.player

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.tween
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.platform.LocalContext
import androidx.palette.graphics.Palette
import coil3.SingletonImageLoader
import coil3.request.ImageRequest
import coil3.request.SuccessResult
import coil3.request.allowHardware
import coil3.toBitmap
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/** The full player's colours, taken from the artwork (SPEC §5). Text is always light on them. */
@Immutable
data class PlayerColors(val top: Color, val bottom: Color, val content: Color = Color.White)

/** Before the artwork's colours are known, or when it has none (no cover, no server). */
val DefaultPlayerColors =
    PlayerColors(top = Color(color = 0xFF3A3A40), bottom = Color(color = 0xFF101012))

/** How much black is mixed into the artwork's colours so white text stays readable. */
private const val TOP_DARKEN = 0.35f
private const val BOTTOM_DARKEN = 0.7f

/** Size in pixels of the copy of the artwork that Palette reads. */
private const val PALETTE_SAMPLE_PX = 128

private const val COLOR_ANIMATION_MS = 600

/**
 * The player colours for an artwork whose dominant colour is [dominant] and darkest muted colour
 * is [darkMuted] (ARGB, as Palette returns them; null when Palette found none).
 */
fun playerColorsFrom(dominant: Int?, darkMuted: Int?): PlayerColors {
    if (dominant == null) return DefaultPlayerColors
    val base = Color(dominant)
    val deep = Color(darkMuted ?: dominant)
    return PlayerColors(
        top = lerp(base, Color.Black, TOP_DARKEN),
        bottom = lerp(deep, Color.Black, BOTTOM_DARKEN)
    )
}

/**
 * The colours of the artwork at [url], read with Palette off the main thread and animated when
 * the song changes. Uses the app's image loader, so the cover comes from its cache and through
 * the authenticated OkHttp client.
 */
@Composable
fun rememberPlayerColors(url: String?): PlayerColors {
    val context = LocalContext.current
    var colors by remember { mutableStateOf(DefaultPlayerColors) }
    LaunchedEffect(url) {
        if (url == null) {
            colors = DefaultPlayerColors
            return@LaunchedEffect
        }
        val request = ImageRequest.Builder(context)
            .data(url)
            .size(PALETTE_SAMPLE_PX)
            .allowHardware(false)
            .build()
        val result = SingletonImageLoader.get(context).execute(request)
        val bitmap = (result as? SuccessResult)?.image?.toBitmap(
            PALETTE_SAMPLE_PX,
            PALETTE_SAMPLE_PX
        )
        colors = if (bitmap == null) {
            DefaultPlayerColors
        } else {
            withContext(Dispatchers.Default) {
                val palette = Palette.from(bitmap).generate()
                playerColorsFrom(palette.dominantSwatch?.rgb, palette.darkMutedSwatch?.rgb)
            }
        }
    }
    val top by animateColorAsState(colors.top, tween(COLOR_ANIMATION_MS), label = "playerTop")
    val bottom by animateColorAsState(
        colors.bottom,
        tween(COLOR_ANIMATION_MS),
        label = "playerBottom"
    )
    return PlayerColors(top = top, bottom = bottom, content = colors.content)
}
