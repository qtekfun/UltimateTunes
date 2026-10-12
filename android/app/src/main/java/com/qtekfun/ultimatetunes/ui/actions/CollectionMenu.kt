// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.actions

import androidx.compose.foundation.layout.padding
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import com.qtekfun.ultimatetunes.ui.theme.Dimens

/** Test tags of the album and playlist menus. */
const val COLLECTION_OFFLINE_TAG = "collection.offline"
const val COLLECTION_ADD_TAG = "collection.addToPlaylist"
const val COLLECTION_EXPORT_TAG = "collection.export"

/**
 * The entries album and playlist menus share: keep offline (RF-12), add all songs to a playlist,
 * export them to the phone (RF-14). [close] closes the menu first.
 */
@Composable
fun CollectionMenuItems(
    tracks: List<TrackTile>,
    isOffline: Boolean,
    onToggleOffline: () -> Unit,
    close: () -> Unit
) {
    val actions = LocalCollectionActions.current
    val offlineLabel =
        if (isOffline) R.string.collection_stop_offline else R.string.collection_keep_offline
    DropdownMenuItem(
        text = { Text(stringResource(offlineLabel)) },
        leadingIcon = {
            Icon(
                painterResource(if (isOffline) R.drawable.ic_delete else R.drawable.ic_download),
                contentDescription = null
            )
        },
        onClick = {
            close()
            onToggleOffline()
        },
        modifier = Modifier.testTag(COLLECTION_OFFLINE_TAG)
    )
    if (tracks.isNotEmpty()) {
        DropdownMenuItem(
            text = { Text(stringResource(R.string.menu_add_to_playlist)) },
            leadingIcon = { Icon(painterResource(R.drawable.ic_add), contentDescription = null) },
            onClick = {
                close()
                actions.addToPlaylist(tracks)
            },
            modifier = Modifier.testTag(COLLECTION_ADD_TAG)
        )
        DropdownMenuItem(
            text = { Text(stringResource(R.string.menu_export)) },
            leadingIcon = {
                Icon(painterResource(R.drawable.ic_upload), contentDescription = null)
            },
            onClick = {
                close()
                actions.export(tracks)
            },
            modifier = Modifier.testTag(COLLECTION_EXPORT_TAG)
        )
    }
}

/** "Kept offline: new songs download automatically", under an album's or playlist's header. */
@Composable
fun OfflineNote(isOffline: Boolean) {
    if (!isOffline) return
    Text(
        text = stringResource(R.string.collection_offline),
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.primary,
        modifier = Modifier.padding(horizontal = Dimens.ScreenMargin)
    )
}
