// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.player

import androidx.compose.animation.core.Animatable
import androidx.compose.foundation.gestures.detectVerticalDragGestures
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.util.VelocityTracker
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch

/** Downward drag that closes the full player. */
private val CollapseThreshold = 120.dp

/** A downward flick faster than this closes the full player whatever the distance. */
private val CollapseFlingVelocity = 1200.dp

/** The downward offset of the full player while the user drags it. */
internal class CollapseDrag(
    val offset: Animatable<Float, *>,
    val scope: CoroutineScope,
    val threshold: Float,
    val flingVelocity: Float
)

/** Puts the player back in place whenever it is [shown] again. */
@Composable
internal fun rememberCollapseDrag(shown: Boolean): CollapseDrag {
    val density = LocalDensity.current
    val offset = remember { Animatable(0f) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(shown) { if (shown) offset.snapTo(0f) }
    return remember(offset, scope, density) {
        CollapseDrag(
            offset = offset,
            scope = scope,
            threshold = with(density) { CollapseThreshold.toPx() },
            flingVelocity = with(density) { CollapseFlingVelocity.toPx() }
        )
    }
}

/**
 * The player follows the finger down; past the threshold or on a fast flick it calls [onCollapse],
 * otherwise it springs back.
 */
internal fun Modifier.collapseOnDrag(drag: CollapseDrag, onCollapse: () -> Unit): Modifier =
    pointerInput(drag) {
        val velocity = VelocityTracker()
        detectVerticalDragGestures(
            onDragStart = { velocity.resetTracking() },
            onDragEnd = {
                val flung = velocity.calculateVelocity().y > drag.flingVelocity
                if (drag.offset.value > drag.threshold || flung) {
                    onCollapse()
                } else {
                    drag.scope.launch { drag.offset.animateTo(0f) }
                }
            },
            onDragCancel = { drag.scope.launch { drag.offset.animateTo(0f) } }
        ) { change, dragAmount ->
            change.consume()
            velocity.addPosition(change.uptimeMillis, change.position)
            drag.scope.launch {
                drag.offset.snapTo((drag.offset.value + dragAmount).coerceAtLeast(0f))
            }
        }
    }
