// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.designsystem

import com.qtekfun.ultimatetunes.ui.model.RefreshState

/** How a screen refreshes by pulling down. */
data class PageRefresh(
    val state: RefreshState = RefreshState(),
    val refresh: () -> Unit = {},
    val messageShown: () -> Unit = {}
)
