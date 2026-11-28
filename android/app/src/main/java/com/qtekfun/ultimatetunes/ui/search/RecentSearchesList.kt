// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.search

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.ui.designsystem.SectionHeader
import com.qtekfun.ultimatetunes.ui.theme.Dimens

/** Test tag of the button that forgets every recent search. */
const val SEARCH_RECENTS_CLEAR_TAG = "search.recents.clear"

/** The recent searches the Search tab shows while the field is empty, and what to do with them. */
data class RecentSearches(
    val queries: List<String> = emptyList(),
    val onRun: (String) -> Unit = {},
    val onRemove: (String) -> Unit = {},
    val onClear: () -> Unit = {},
    /** A result was opened: what led to it is worth remembering. */
    val onResultOpened: () -> Unit = {}
)

internal fun LazyListScope.recentSearches(recents: RecentSearches) {
    item { SectionHeader(stringResource(R.string.search_recent)) }
    items(recents.queries, key = { "recent-$it" }) { query ->
        RecentSearchRow(query, recents.onRun, recents.onRemove)
    }
    item {
        TextButton(
            onClick = recents.onClear,
            modifier = Modifier
                .padding(horizontal = Dimens.SpaceS)
                .testTag(SEARCH_RECENTS_CLEAR_TAG)
        ) {
            Text(stringResource(R.string.search_recent_clear))
        }
    }
}

@Composable
private fun RecentSearchRow(query: String, onRun: (String) -> Unit, onRemove: (String) -> Unit) {
    val focus = LocalFocusManager.current
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .fillMaxWidth()
            .clickable {
                focus.clearFocus()
                onRun(query)
            }
            .padding(start = Dimens.ScreenMargin, end = Dimens.SpaceS)
    ) {
        Icon(painter = painterResource(R.drawable.ic_search), contentDescription = null)
        Text(
            text = query,
            style = MaterialTheme.typography.bodyLarge,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier
                .weight(1f)
                .padding(horizontal = Dimens.SpaceM)
        )
        IconButton(onClick = { onRemove(query) }) {
            Icon(
                painter = painterResource(R.drawable.ic_close),
                contentDescription = stringResource(R.string.search_recent_remove, query)
            )
        }
    }
}
