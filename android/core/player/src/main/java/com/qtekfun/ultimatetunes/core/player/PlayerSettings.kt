// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player

import com.qtekfun.ultimatetunes.core.player.cache.CachePolicy
import kotlinx.coroutines.flow.Flow

/** The device's playback choices the player follows (RF-12; edited in the app's Settings). */
data class PlayerSettings(
    /** Size of the play cache in MB. */
    val cacheSizeMb: Int = CachePolicy.DEFAULT_CACHE_MB,
    /** Only cached and downloaded music: no prefetch and no network for playback extras. */
    val offlineOnly: Boolean = false,
    /** Offline downloads and their sync wait for an unmetered network. */
    val downloadOnWifiOnly: Boolean = true
)

/** Where the player reads [PlayerSettings]; the app binds it to its settings store. */
interface PlayerSettingsSource {
    val settings: Flow<PlayerSettings>
}
