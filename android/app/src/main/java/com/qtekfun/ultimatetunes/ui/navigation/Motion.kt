// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.navigation

import androidx.compose.animation.AnimatedContentTransitionScope
import androidx.compose.animation.EnterTransition
import androidx.compose.animation.ExitTransition
import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.VisibilityThreshold
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.unit.IntOffset
import androidx.navigation.NavBackStackEntry

private const val PUSH_MS = 300
private const val TAB_FADE_MS = 90

/** How much of its width the screen underneath moves while another one covers it. */
private const val PARALLAX = 4

/** Starts fast and settles gently. */
@Suppress("MagicNumber") // The control points of the curve.
private val PushEasing = CubicBezierEasing(0.2f, 0f, 0f, 1f)

private val push = tween<IntOffset>(PUSH_MS, easing = PushEasing)

/** The full player and its artwork move with a spring, without bouncing. */
internal val PlayerSlideSpring = spring(
    stiffness = Spring.StiffnessMediumLow,
    visibilityThreshold = IntOffset.VisibilityThreshold
)
internal val PlayerArtworkSpring = spring(
    stiffness = Spring.StiffnessMediumLow,
    visibilityThreshold = Rect.VisibilityThreshold
)

/** Each tab is its own graph, so a change of parent is a change of tab. */
private fun AnimatedContentTransitionScope<NavBackStackEntry>.changesTab() =
    initialState.destination.parent?.route != targetState.destination.parent?.route

/** A new screen comes in from the end side; another tab just appears. */
internal fun AnimatedContentTransitionScope<NavBackStackEntry>.screenEnter(): EnterTransition =
    if (changesTab()) {
        fadeIn(tween(TAB_FADE_MS))
    } else {
        slideInHorizontally(push) { it }
    }

internal fun AnimatedContentTransitionScope<NavBackStackEntry>.screenExit(): ExitTransition =
    if (changesTab()) {
        fadeOut(tween(TAB_FADE_MS))
    } else {
        slideOutHorizontally(push) { -it / PARALLAX }
    }

internal fun AnimatedContentTransitionScope<NavBackStackEntry>.screenPopEnter(): EnterTransition =
    if (changesTab()) {
        fadeIn(tween(TAB_FADE_MS))
    } else {
        slideInHorizontally(push) { -it / PARALLAX }
    }

internal fun AnimatedContentTransitionScope<NavBackStackEntry>.screenPopExit(): ExitTransition =
    if (changesTab()) {
        fadeOut(tween(TAB_FADE_MS))
    } else {
        slideOutHorizontally(push) { it }
    }
