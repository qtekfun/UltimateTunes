// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.actions

import androidx.compose.foundation.layout.Box
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.ui.designsystem.LocalAvailability
import com.qtekfun.ultimatetunes.ui.designsystem.OverflowButton
import com.qtekfun.ultimatetunes.ui.model.TrackTile

/**
 * The overflow button of a playlist or artist row and its menu: play, shuffle and the entries of
 * every collection. Its songs ([load]) are only read once the menu opens. [onToggleOffline] is
 * null for what cannot be kept offline.
 */
@Composable
fun CollectionOverflow(
    title: String,
    load: suspend () -> List<TrackTile>,
    onPlay: (List<TrackTile>, Int) -> Unit,
    isOffline: Boolean = false,
    onToggleOffline: (() -> Unit)? = null
) {
    var open by remember { mutableStateOf(false) }
    var tracks by remember { mutableStateOf(emptyList<TrackTile>()) }
    LaunchedEffect(open) { if (open) tracks = load() }
    val availability = LocalAvailability.current
    val close = { open = false }
    Box {
        OverflowButton(title, onClick = { open = true })
        DropdownMenu(expanded = open, onDismissRequest = close) {
            if (tracks.isNotEmpty()) {
                DropdownMenuItem(
                    text = { Text(stringResource(R.string.play)) },
                    leadingIcon = {
                        Icon(painterResource(R.drawable.ic_play), contentDescription = null)
                    },
                    onClick = {
                        close()
                        onPlay(availability.playable(tracks), 0)
                    }
                )
                DropdownMenuItem(
                    text = { Text(stringResource(R.string.shuffle)) },
                    leadingIcon = {
                        Icon(painterResource(R.drawable.ic_shuffle), contentDescription = null)
                    },
                    onClick = {
                        close()
                        onPlay(availability.playable(tracks).shuffled(), 0)
                    }
                )
            }
            CollectionMenuItems(tracks, isOffline, onToggleOffline, close)
        }
    }
}
