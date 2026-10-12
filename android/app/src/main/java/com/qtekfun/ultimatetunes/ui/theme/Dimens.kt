// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.theme

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.unit.dp

/** Spacing, sizes and shapes of the design system: generous margins, rounded artwork. */
object Dimens {
    /** Horizontal margin of every screen. */
    val ScreenMargin = 20.dp
    val SpaceXS = 4.dp
    val SpaceS = 8.dp
    val SpaceM = 12.dp
    val SpaceL = 16.dp
    val SpaceXL = 24.dp
    val SpaceXXL = 32.dp

    /** Width of an album tile in a horizontal shelf. */
    val ShelfTile = 164.dp

    /** Width of a station tile (wider, landscape-ish). */
    val StationTile = 260.dp

    /** Artwork of a track row and of the mini player. */
    val RowArtwork = 48.dp
    val MiniArtwork = 44.dp

    /** Minimum touch target height for rows (TalkBack and large fonts). */
    val MinRowHeight = 56.dp
    val MiniPlayerHeight = 64.dp

    val ArtworkCorner = 10.dp
    val SmallArtworkCorner = 6.dp
    val PlayerArtworkCorner = 14.dp
    val CardCorner = 16.dp

    val ArtworkShape = RoundedCornerShape(ArtworkCorner)
    val SmallArtworkShape = RoundedCornerShape(SmallArtworkCorner)
    val PlayerArtworkShape = RoundedCornerShape(PlayerArtworkCorner)
    val CardShape = RoundedCornerShape(CardCorner)
    val PillShape = RoundedCornerShape(percent = 50)
}
