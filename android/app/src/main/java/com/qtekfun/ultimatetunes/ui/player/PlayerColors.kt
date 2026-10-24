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
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.platform.LocalContext
import androidx.palette.graphics.Palette
import coil3.SingletonImageLoader
import coil3.request.ImageRequest
import coil3.request.SuccessResult
import coil3.request.allowHardware
import coil3.toBitmap
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * The full player's colours, taken from the artwork (SPEC §5). Text is always light on them;
 * [accent] (the artist, the play button) is the artwork's liveliest colour, lightened until it
 * reads on [bottom].
 */
@Immutable
data class PlayerColors(
    val top: Color,
    val bottom: Color,
    val content: Color = Color.White,
    val accent: Color = DEFAULT_ACCENT
)

private val DEFAULT_ACCENT = Color(color = 0xFFF2CC8F)

/** Before the artwork's colours are known, or when it has none (no cover, no server). */
val DefaultPlayerColors =
    PlayerColors(top = Color(color = 0xFF3A3A40), bottom = Color(color = 0xFF101012))

/** WCAG contrast the accent keeps against the background, as for body text. */
private const val ACCENT_MIN_CONTRAST = 4.5f
private const val ACCENT_LIGHTEN_STEP = 0.1f

/** How much black is mixed into the artwork's colours so white text stays readable. */
private const val TOP_DARKEN = 0.35f
private const val BOTTOM_DARKEN = 0.7f

/** Size in pixels of the copy of the artwork that Palette reads. */
private const val PALETTE_SAMPLE_PX = 128

private const val COLOR_ANIMATION_MS = 600

/**
 * The player colours for an artwork whose dominant colour is [dominant], darkest muted colour is
 * [darkMuted] and liveliest colour is [vibrant] (ARGB, as Palette returns them; null when Palette
 * found none).
 */
fun playerColorsFrom(dominant: Int?, darkMuted: Int?, vibrant: Int? = null): PlayerColors {
    if (dominant == null) return DefaultPlayerColors
    val base = Color(dominant)
    val deep = Color(darkMuted ?: dominant)
    val bottom = lerp(deep, Color.Black, BOTTOM_DARKEN)
    return PlayerColors(
        top = lerp(base, Color.Black, TOP_DARKEN),
        bottom = bottom,
        accent = readableOn(Color(vibrant ?: dominant), bottom)
    )
}

/** [color] mixed with white, as little as needed, until it has enough contrast on [background]. */
internal fun readableOn(color: Color, background: Color): Color {
    var amount = 0f
    var mixed = color
    while (contrast(mixed, background) < ACCENT_MIN_CONTRAST && amount < 1f) {
        amount = (amount + ACCENT_LIGHTEN_STEP).coerceAtMost(1f)
        mixed = lerp(color, Color.White, amount)
    }
    return mixed
}

/** WCAG 2 contrast ratio of two opaque colours. */
internal fun contrast(a: Color, b: Color): Float {
    val (light, dark) = listOf(a.luminance(), b.luminance()).sortedDescending()
    return (light + RELATIVE_LUMINANCE_OFFSET) / (dark + RELATIVE_LUMINANCE_OFFSET)
}

private const val RELATIVE_LUMINANCE_OFFSET = 0.05f

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
                playerColorsFrom(
                    palette.dominantSwatch?.rgb,
                    palette.darkMutedSwatch?.rgb,
                    (palette.lightVibrantSwatch ?: palette.vibrantSwatch)?.rgb
                )
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
