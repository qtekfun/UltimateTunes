// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.library

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.tooling.preview.Preview
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.ui.designsystem.LargeTitleScaffold
import com.qtekfun.ultimatetunes.ui.designsystem.MessageState
import com.qtekfun.ultimatetunes.ui.theme.UltimateTunesTheme

/** The Library tab's frame; its content (artists, albums, playlists…) is PLAN T13. */
@Composable
fun LibraryScreen(contentPadding: PaddingValues, modifier: Modifier = Modifier) {
    LargeTitleScaffold(title = stringResource(R.string.tab_library), modifier = modifier) { inner ->
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(
                top = inner.calculateTopPadding(),
                bottom = contentPadding.calculateBottomPadding()
            )
        ) {
            item {
                MessageState(
                    message = stringResource(R.string.library_placeholder),
                    icon = R.drawable.ic_library
                )
            }
        }
    }
}

@Preview(showBackground = true)
@Composable
private fun LibraryPreview() {
    UltimateTunesTheme { LibraryScreen(PaddingValues()) }
}
