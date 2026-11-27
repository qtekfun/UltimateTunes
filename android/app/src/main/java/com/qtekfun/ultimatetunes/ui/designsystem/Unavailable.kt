// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.designsystem

import androidx.compose.runtime.Composable
import androidx.compose.runtime.compositionLocalOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.res.stringResource
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.availability.Availability

/** What can play now, for rows and tiles to dim the rest and offline mode to leave it out. */
val LocalAvailability = compositionLocalOf { Availability() }

/** How visible something is that cannot play now. */
private const val DIMMED_ALPHA = 0.38f

/** Dimmed unless it is [available]. */
fun Modifier.availableOrDimmed(available: Boolean): Modifier =
    if (available) this else alpha(DIMMED_ALPHA)

/** [description] as TalkBack reads it: with a note when it is not [available]. */
@Composable
fun availabilityDescription(description: String, available: Boolean): String {
    val note = stringResource(R.string.not_on_phone)
    return if (available) description else "$description, $note"
}
