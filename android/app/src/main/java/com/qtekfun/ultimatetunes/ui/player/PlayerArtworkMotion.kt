// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.player

import androidx.compose.runtime.compositionLocalOf
import androidx.compose.ui.Modifier

/**
 * Applied to the artwork of the mini player and of the full player, so that the one grows into
 * the other. The main screen provides it; on its own, each player has none.
 */
val LocalPlayerArtworkMotion = compositionLocalOf<Modifier> { Modifier }
