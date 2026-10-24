// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.player

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.ProgressBarRangeInfo
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.disabled
import androidx.compose.ui.semantics.progressBarRangeInfo
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.setProgress
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.ui.model.formatDuration
import com.qtekfun.ultimatetunes.ui.theme.Dimens
import kotlin.random.Random

private const val MILLIS_PER_SECOND = 1000L

/** Width of one bar and the gap after it. */
private val BarWidth = 3.dp
private val BarGap = 2.dp
private val ScrubberHeight = 36.dp

/** Bars are never shorter than this share of the height, so the line always reads. */
private const val MIN_BAR = 0.28f

/** Opacity of the bars still to play. */
private const val UNPLAYED_ALPHA = 0.28f

/**
 * The heights (0..1) of [count] bars for the song [seed]: the same song always gets the same
 * shape. Decoration only, not the song's loudness (the app has no waveform of it); each bar is
 * smoothed with its neighbour so the line looks like one.
 */
fun barHeights(seed: String, count: Int): List<Float> {
    if (count <= 0) return emptyList()
    val random = Random(seed.hashCode())
    val raw = List(count) { random.nextFloat() }
    return raw.mapIndexed { i, value ->
        val neighbour = raw.getOrElse(i - 1) { value }
        MIN_BAR + (1f - MIN_BAR) * (value + neighbour) / 2f
    }
}

/**
 * The full player's scrubber (SPEC §5): a row of bars, the played ones in [accent]. Tap or drag
 * to seek; the seek happens once, on release. TalkBack sees it as a slider over the song.
 */
@Composable
internal fun BarScrubber(
    state: PlayerUiState,
    seed: String,
    accent: Color,
    onSeek: (Long) -> Unit
) {
    val content = LocalContentColor.current
    val durationMs = state.durationMs.coerceAtLeast(0)
    var dragging by remember { mutableStateOf<Float?>(null) }
    val fraction = dragging ?: if (durationMs > 0) {
        (state.positionMs.toFloat() / durationMs).coerceIn(0f, 1f)
    } else {
        0f
    }
    val positionMs = (fraction * durationMs).toLong()
    val seek by rememberUpdatedState(onSeek)
    val duration by rememberUpdatedState(durationMs)
    val elapsed = formatDuration((positionMs / MILLIS_PER_SECOND).toInt())
    val total = formatDuration((durationMs / MILLIS_PER_SECOND).toInt())
    val label = stringResource(R.string.player_position)
    val position = stringResource(R.string.player_position_state, elapsed, total)
    val gestures = if (state.canSeek) {
        Modifier.scrubGestures(
            onDrag = { dragging = it },
            onSeek = { at -> seek((at * duration).toLong()) }
        )
    } else {
        Modifier
    }
    Column(modifier = Modifier.fillMaxWidth().padding(top = Dimens.SpaceL)) {
        Canvas(
            modifier = Modifier
                .fillMaxWidth()
                .height(ScrubberHeight)
                .then(gestures)
                .testTag(PLAYER_SCRUBBER_TAG)
                .semantics {
                    contentDescription = label
                    stateDescription = position
                    progressBarRangeInfo = ProgressBarRangeInfo(fraction, 0f..1f)
                    if (state.canSeek) {
                        setProgress { target ->
                            seek((target.coerceIn(0f, 1f) * duration).toLong())
                            true
                        }
                    } else {
                        disabled()
                    }
                }
        ) { drawBars(seed, fraction, accent, content.copy(alpha = UNPLAYED_ALPHA)) }
        Times(
            elapsed = elapsed,
            remaining = formatDuration(((durationMs - positionMs) / MILLIS_PER_SECOND).toInt())
        )
    }
}

/**
 * Tap to seek, or drag and seek on release: [onDrag] gets the finger's place as a share of the
 * width while dragging (null when it ends), [onSeek] the share to seek to.
 */
private fun Modifier.scrubGestures(onDrag: (Float?) -> Unit, onSeek: (Float) -> Unit): Modifier {
    var last: Float? = null
    return pointerInput(Unit) {
        detectTapGestures { offset -> onSeek((offset.x / size.width).coerceIn(0f, 1f)) }
    }.pointerInput(Unit) {
        detectHorizontalDragGestures(
            onDragStart = {
                last = (it.x / size.width).coerceIn(0f, 1f)
                onDrag(last)
            },
            onDragEnd = {
                last?.let(onSeek)
                last = null
                onDrag(null)
            },
            onDragCancel = {
                last = null
                onDrag(null)
            }
        ) { change, _ ->
            last = (change.position.x / size.width).coerceIn(0f, 1f)
            onDrag(last)
        }
    }
}

@Composable
private fun Times(elapsed: String, remaining: String) {
    val color = LocalContentColor.current.copy(alpha = 0.7f)
    Row(
        modifier = Modifier.fillMaxWidth().padding(top = Dimens.SpaceXS),
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Text(
            text = elapsed,
            style = MaterialTheme.typography.labelMedium,
            fontWeight = FontWeight.SemiBold,
            color = color
        )
        Text(
            text = stringResource(R.string.player_remaining, remaining),
            style = MaterialTheme.typography.labelMedium,
            fontWeight = FontWeight.SemiBold,
            color = color
        )
    }
}

/** The bars across the width, those up to [fraction] in [played], the rest in [unplayed]. */
private fun DrawScope.drawBars(seed: String, fraction: Float, played: Color, unplayed: Color) {
    val step = (BarWidth + BarGap).toPx()
    val count = ((size.width + BarGap.toPx()) / step).toInt()
    val playedBars = (fraction * count).toInt()
    barHeights(seed, count).forEachIndexed { i, h ->
        val barHeight = size.height * h
        drawRoundRect(
            color = if (i < playedBars) played else unplayed,
            topLeft = Offset(i * step, (size.height - barHeight) / 2f),
            size = Size(BarWidth.toPx(), barHeight),
            cornerRadius = CornerRadius(BarWidth.toPx() / 2f)
        )
    }
}
