// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.designsystem

import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.wrapContentWidth
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.Dp

/** A square cover taking [fraction] of the width, never wider than [max], centred. */
fun Modifier.coverSize(fraction: Float, max: Dp): Modifier =
    fillMaxWidth(fraction).wrapContentWidth().widthIn(max = max).aspectRatio(1f)
