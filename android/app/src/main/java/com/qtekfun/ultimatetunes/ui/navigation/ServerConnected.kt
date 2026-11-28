// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.navigation

import com.qtekfun.ultimatetunes.playback.OfflineControls
import com.qtekfun.ultimatetunes.ui.search.RecentSearchesStore
import javax.inject.Inject

/**
 * What this phone does each time the app is connected to a server: drops what another one left
 * (recent searches, downloads) and goes on with a download sync the process death stopped.
 */
class ServerConnected @Inject constructor(
    private val offline: OfflineControls,
    private val recentSearches: RecentSearchesStore
) {
    suspend operator fun invoke(server: String) {
        recentSearches.serverConnected(server)
        offline.serverConnected(server)
    }
}
