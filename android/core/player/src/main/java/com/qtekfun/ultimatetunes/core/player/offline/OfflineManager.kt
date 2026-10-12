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
        if (selection.keepsTrack(track.id)) {
            selection
        } else {
            selection.copy(
                tracks =
                    selection.tracks + track
            )
        }
    }

    suspend fun dropTrack(id: SongId) = change {
        it.copy(
            tracks = it.tracks.filterNot { t ->
                t.id ==
                    id
            }
        )
    }

    suspend fun keepCollection(kind: CollectionKind, id: String, name: String) =
        change { selection ->
            if (selection.keepsCollection(kind, id)) {
                selection
            } else {
                selection.copy(
                    collections =
                        selection.collections + OfflineCollection(kind, id, name)
                )
            }
        }

    suspend fun dropCollection(kind: CollectionKind, id: String) = change { selection ->
        selection.copy(
            collections = selection.collections.filterNot {
                it.kind == kind &&
                    it.id == id
            }
        )
    }

    /** Syncs as soon as the network allows (and periodically), e.g. after a settings change. */
    suspend fun syncSoon() {
        if (store.selection.first().isEmpty) {
            scheduler.cancel()
        } else {
            scheduler.schedule(settings.settings.first().downloadOnWifiOnly)
        }
    }

    private suspend fun change(transform: (OfflineSelection) -> OfflineSelection) {
        store.update(transform)
        // Dropped songs are freed at once, without waiting for the network.
        syncer.prune()
        syncSoon()
    }
}
