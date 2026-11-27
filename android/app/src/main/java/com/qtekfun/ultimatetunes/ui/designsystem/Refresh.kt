// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.designsystem

import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier

/**
 * Pull to refresh around a screen's list, under its header ([padding] is the scaffold's). A
 * refresh that fails says so and leaves what is shown.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RefreshBox(
    pull: PageRefresh,
    padding: PaddingValues,
    snackbar: ScreenSnackbar,
    content: @Composable BoxScope.() -> Unit
) {
    MessageEffect(pull.state.error, snackbar.state, pull.messageShown)
    PullToRefreshBox(
        isRefreshing = pull.state.refreshing,
        onRefresh = pull.refresh,
        modifier = Modifier.padding(top = padding.calculateTopPadding()).fillMaxSize(),
        content = content
    )
}
