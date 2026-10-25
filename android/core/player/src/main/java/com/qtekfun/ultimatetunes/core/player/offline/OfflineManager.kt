// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.offline

import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.player.PlayableTrack
import com.qtekfun.ultimatetunes.core.player.PlayerSettingsSource
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

/**
 * What the app's screens use for offline music (RF-12): keep or drop a song, an album or a
 * playlist, and watch the downloads. Every change schedules a sync, which does the downloading.
 */
@Singleton
class OfflineManager @Inject constructor(
    private val store: OfflineSelectionStore,
    private val downloads: OfflineDownloads,
    private val syncer: OfflineSyncer,
    private val scheduler: OfflineSyncScheduler,
    private val settings: PlayerSettingsSource
) {
    /** What is kept. */
    val selection: Flow<OfflineSelection> = store.selection

    /** Every download with its state, newest first. */
    val items: StateFlow<List<OfflineItem>> get() = downloads.items

    suspend fun keepTrack(track: PlayableTrack) = change { selection ->
        val tracks = if (selection.keepsTrack(track.id)) {
            selection.tracks
        } else {
            selection.tracks +
                track
        }
        selection.copy(tracks = tracks)
    }

    suspend fun dropTrack(id: SongId) = change(dropped = { setOf(id) }) { selection ->
        selection.copy(tracks = selection.tracks.filterNot { it.id == id })
    }

    suspend fun keepCollection(kind: CollectionKind, id: String, name: String) =
        change { selection ->
            val kept = selection.keepsCollection(kind, id)
            val added = if (kept) emptyList() else listOf(OfflineCollection(kind, id, name))
            selection.copy(collections = selection.collections + added)
        }

    suspend fun dropCollection(kind: CollectionKind, id: String) = change(
        dropped = { selection ->
            selection.collections.filter { it.matches(kind, id) }
                .flatMap { it.members.orEmpty() }
                .mapTo(HashSet()) { it.id }
        }
    ) { selection ->
        selection.copy(collections = selection.collections.filterNot { it.matches(kind, id) })
    }

    /** The whole library kept offline; null when the setting is off. */
    val library: Flow<LibraryOffline?> = store.selection.map { it.library }

    /** Reads the library from the server (for the size shown before the setting is on). */
    suspend fun scanLibrary(): LibraryScan? = syncer.readLibrary()

    /** How [scan] fits [limitBytes], not counting the songs the user keeps on their own. */
    suspend fun libraryReport(scan: LibraryScan, limitBytes: Long): LibraryReport =
        scan.report(limitBytes, store.selection.first().explicitIds())

    /**
     * Applies "Keep my whole library offline" and its limit as the settings now are. Turned off,
     * the songs kept only because of it are freed at once (explicit ones stay); turned on or with
     * a new limit, a sync is scheduled.
     */
    suspend fun libraryOfflineChanged() {
        val on = settings.settings.first().libraryOffline
        var freed = emptySet<SongId>()
        store.update { before ->
            if (on) {
                before.copy(library = before.library ?: LibraryOffline())
            } else {
                freed = before.library?.songs.orEmpty().mapTo(HashSet()) { it.id }
                before.copy(library = null)
            }
        }
        syncer.prune(freed)
        syncSoon()
    }

    /** Syncs as soon as the network allows (and periodically), e.g. after a settings change. */
    suspend fun syncSoon() {
        if (store.selection.first().isEmpty) {
            scheduler.cancel()
        } else {
            scheduler.schedule(settings.settings.first().downloadOnWifiOnly)
        }
    }

    private suspend fun change(
        dropped: (OfflineSelection) -> Set<SongId> = { emptySet() },
        transform: (OfflineSelection) -> OfflineSelection
    ) {
        var freed = emptySet<SongId>()
        store.update { before ->
            freed = dropped(before)
            transform(before)
        }
        // Dropped songs are freed at once, without waiting for the network.
        syncer.prune(freed)
        syncSoon()
    }

    private fun OfflineCollection.matches(kind: CollectionKind, id: String) =
        this.kind == kind && this.id == id
}
