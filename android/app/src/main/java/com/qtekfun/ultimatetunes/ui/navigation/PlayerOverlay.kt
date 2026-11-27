// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.navigation

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.EnterExitState
import androidx.compose.animation.SharedTransitionScope
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import com.qtekfun.ultimatetunes.ui.lyrics.LyricsHooks
import com.qtekfun.ultimatetunes.ui.player.FullPlayer
import com.qtekfun.ultimatetunes.ui.player.LocalPlayerArtworkMotion
import com.qtekfun.ultimatetunes.ui.player.PlayerActions
import com.qtekfun.ultimatetunes.ui.player.PlayerUiState

/** Pairs the artwork of the mini player with the one of the full player. */
private const val PLAYER_ARTWORK_KEY = "playerArtwork"

/** Gives the mini player in [content] the artwork that grows into the full player's. */
@Composable
internal fun SharedTransitionScope.MiniArtworkMotion(
    expanded: Boolean,
    content: @Composable () -> Unit
) {
    val artwork = Modifier.sharedElementWithCallerManagedVisibility(
        sharedContentState = rememberSharedContentState(PLAYER_ARTWORK_KEY),
        visible = !expanded,
        boundsTransform = { _, _ -> PlayerArtworkSpring }
    )
    CompositionLocalProvider(LocalPlayerArtworkMotion provides artwork, content = content)
}

/** The full player sliding over the tabs, its artwork growing out of the mini player's. */
@Composable
internal fun SharedTransitionScope.FullPlayerOverlay(
    visible: Boolean,
    player: PlayerUiState,
    actions: PlayerActions,
    lyrics: LyricsHooks,
    onCollapse: () -> Unit
) {
    AnimatedVisibility(
        visible = visible,
        enter = slideInVertically(PlayerSlideSpring) { it },
        exit = slideOutVertically(PlayerSlideSpring) { it }
    ) {
        val artwork = Modifier.sharedElement(
            sharedContentState = rememberSharedContentState(PLAYER_ARTWORK_KEY),
            animatedVisibilityScope = this,
            boundsTransform = { _, _ -> PlayerArtworkSpring }
        )
        val shown = transition.targetState == EnterExitState.Visible
        CompositionLocalProvider(LocalPlayerArtworkMotion provides artwork) {
            FullPlayer(
                state = player,
                actions = actions,
                onCollapse = onCollapse,
                shown = shown,
                lyrics = lyrics
            )
        }
    }
}
