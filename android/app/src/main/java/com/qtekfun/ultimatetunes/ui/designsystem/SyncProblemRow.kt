// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.designsystem

import androidx.compose.runtime.Composable
import com.qtekfun.ultimatetunes.ui.model.LoadError

/**
 * Above a list that shows what is stored: a refused key says so and offers to connect again.
 * Other failures (no connection above all) say nothing: what is shown is what there is.
 */
@Composable
fun SyncProblemRow(error: LoadError) {
    if (error == LoadError.UNAUTHORIZED) ErrorState(error, onRetry = {})
}
