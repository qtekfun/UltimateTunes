// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.library

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.qtekfun.ultimatetunes.ui.designsystem.PageRefresh
import com.qtekfun.ultimatetunes.ui.designsystem.RefreshBox
import com.qtekfun.ultimatetunes.ui.designsystem.ScreenScaffold
import com.qtekfun.ultimatetunes.ui.designsystem.rememberScreenSnackbar
import com.qtekfun.ultimatetunes.ui.navigation.Navigator
import com.qtekfun.ultimatetunes.ui.theme.Dimens

/** A page of the Library: the header with Back and a list. */
@Composable
internal fun LibraryPageScaffold(
    title: String,
    contentPadding: PaddingValues,
    navigator: Navigator,
    pull: PageRefresh? = null,
    content: LazyListScope.() -> Unit
) {
    val snackbar = rememberScreenSnackbar()
    ScreenScaffold(title = title, onBack = navigator.back, snackbarHost = snackbar.host) { inner ->
        val list = @Composable { top: PaddingValues ->
            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(
                    top = top.calculateTopPadding(),
                    bottom = contentPadding.calculateBottomPadding() + Dimens.SpaceXL
                ),
                content = content
            )
        }
        if (pull == null) {
            list(inner)
        } else {
            RefreshBox(pull, inner, snackbar) {
                list(PaddingValues())
            }
        }
    }
}
