// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.library

import com.qtekfun.ultimatetunes.ui.model.TrackTile
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flowOf

/**
 * The songs downloaded for offline listening (RF-12), which the Library's Downloads screen lists.
 * The downloads themselves are PLAN T17 (Media3 downloads); until it binds its own implementation
 * the app uses [NoOfflineDownloads].
 */
interface OfflineLibrary {
    val downloads: Flow<List<TrackTile>>
}

/** No offline downloads (before PLAN T17). */
object NoOfflineDownloads : OfflineLibrary {
    override val downloads: Flow<List<TrackTile>> = flowOf(emptyList())
}
