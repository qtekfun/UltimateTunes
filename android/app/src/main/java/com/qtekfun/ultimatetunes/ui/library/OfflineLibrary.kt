// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.library

import com.qtekfun.ultimatetunes.ui.model.TrackTile
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flowOf

/**
 * The songs downloaded for offline listening (RF-12), which the Library's Downloads screen lists:
 * the Media3 downloads of PLAN T17 (`DownloadsOfflineLibrary`), or [NoOfflineDownloads] in tests.
 */
interface OfflineLibrary {
    val downloads: Flow<List<TrackTile>>
}

/** No offline downloads. */
object NoOfflineDownloads : OfflineLibrary {
    override val downloads: Flow<List<TrackTile>> = flowOf(emptyList())
}
