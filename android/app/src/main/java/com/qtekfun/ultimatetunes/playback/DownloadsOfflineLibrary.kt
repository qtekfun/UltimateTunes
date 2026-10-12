// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.playback

import com.qtekfun.ultimatetunes.core.player.offline.OfflineState
import com.qtekfun.ultimatetunes.ui.library.OfflineLibrary
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import javax.inject.Inject
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

/**
 * The Library's Downloads list from the real offline downloads (RF-12): the songs fully on the
 * phone, newest first. Bound in place of T13's empty `NoOfflineDownloads` (see the PR notes).
 */
class DownloadsOfflineLibrary @Inject constructor(offline: OfflineControls) : OfflineLibrary {
    override val downloads: Flow<List<TrackTile>> = offline.items.map { items ->
        items.filter { it.state == OfflineState.DONE }.map { it.track.toTile() }
    }
}
