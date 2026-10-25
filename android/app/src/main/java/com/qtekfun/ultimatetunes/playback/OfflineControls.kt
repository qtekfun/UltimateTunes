// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.playback

import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.player.PlayableTrack
import com.qtekfun.ultimatetunes.core.player.offline.CollectionKind
import com.qtekfun.ultimatetunes.core.player.offline.LibraryOffline
import com.qtekfun.ultimatetunes.core.player.offline.LibraryReport
import com.qtekfun.ultimatetunes.core.player.offline.LibraryScan
import com.qtekfun.ultimatetunes.core.player.offline.OfflineItem
import com.qtekfun.ultimatetunes.core.player.offline.OfflineManager
import com.qtekfun.ultimatetunes.core.player.offline.OfflineSelection
import javax.inject.Inject
import kotlinx.coroutines.flow.Flow

/**
 * What the screens change of the offline music (RF-12): songs, albums and playlists kept on the
 * phone, which stay in sync with the server. [OfflineManager] is the real one; tests use fakes.
 */
interface OfflineControls {
    /** What is kept. */
    val selection: Flow<OfflineSelection>

    /** Every download with its state. */
    val items: Flow<List<OfflineItem>>

    suspend fun keepTrack(track: PlayableTrack)

    suspend fun dropTrack(id: SongId)

    suspend fun keepCollection(kind: CollectionKind, id: String, name: String)

    suspend fun dropCollection(kind: CollectionKind, id: String)

    /** Syncs again soon, e.g. after the Wi-Fi setting changed. */
    suspend fun syncSoon()

    /** The whole library kept offline; null when "Keep my whole library offline" is off. */
    val library: Flow<LibraryOffline?>

    /** Reads the library from the server to size it; null when the server cannot be reached. */
    suspend fun scanLibrary(): LibraryScan?

    /** How [scan] fits [limitBytes], not counting what the user keeps explicitly. */
    suspend fun libraryReport(scan: LibraryScan, limitBytes: Long): LibraryReport

    /** The library setting or its limit changed: free or sync accordingly. */
    suspend fun libraryOfflineChanged()
}

/** [OfflineControls] of the player's [OfflineManager]. */
class ManagerOfflineControls @Inject constructor(private val manager: OfflineManager) :
    OfflineControls {
    override val selection: Flow<OfflineSelection> get() = manager.selection
    override val items: Flow<List<OfflineItem>> get() = manager.items

    override suspend fun keepTrack(track: PlayableTrack) = manager.keepTrack(track)

    override suspend fun dropTrack(id: SongId) = manager.dropTrack(id)

    override suspend fun keepCollection(kind: CollectionKind, id: String, name: String) =
        manager.keepCollection(kind, id, name)

    override suspend fun dropCollection(kind: CollectionKind, id: String) =
        manager.dropCollection(kind, id)

    override suspend fun syncSoon() = manager.syncSoon()

    override val library: Flow<LibraryOffline?> get() = manager.library

    override suspend fun scanLibrary(): LibraryScan? = manager.scanLibrary()

    override suspend fun libraryReport(scan: LibraryScan, limitBytes: Long): LibraryReport =
        manager.libraryReport(scan, limitBytes)

    override suspend fun libraryOfflineChanged() = manager.libraryOfflineChanged()
}
