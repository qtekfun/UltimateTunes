// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.player

import androidx.compose.runtime.Immutable

/** What the player controls do, passed to the mini and full player as one value. */
@Immutable
data class PlayerActions(
    val togglePlay: () -> Unit = {},
    val next: () -> Unit = {},
    val previous: () -> Unit = {},
    /** Seeks to a position in **milliseconds**. */
    val seekTo: (Long) -> Unit = {},
    val playAt: (Int) -> Unit = {},
    /** A radio from the current song replaces what comes next. */
    val startRadio: () -> Unit = {}
) {
    companion object {
        /** The actions of [viewModel]. */
        fun of(viewModel: PlayerViewModel) = PlayerActions(
            togglePlay = viewModel::togglePlayPause,
            next = viewModel::next,
            previous = viewModel::previous,
            seekTo = viewModel::seekTo,
            playAt = viewModel::playAt,
            startRadio = viewModel::startRadio
        )
    }
}
