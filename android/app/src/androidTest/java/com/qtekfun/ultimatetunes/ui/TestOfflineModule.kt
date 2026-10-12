// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui

import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.player.PlayableTrack
import com.qtekfun.ultimatetunes.core.player.offline.CollectionKind
import com.qtekfun.ultimatetunes.core.player.offline.OfflineCollection
import com.qtekfun.ultimatetunes.core.player.offline.OfflineItem
import com.qtekfun.ultimatetunes.core.player.offline.OfflineSelection
import com.qtekfun.ultimatetunes.playback.OfflineControls
import com.qtekfun.ultimatetunes.playback.OfflineControlsModule
import dagger.Module
import dagger.Provides
import dagger.hilt.components.SingletonComponent
import dagger.hilt.testing.TestInstallIn
import javax.inject.Singleton
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update

/**
 * UI tests keep the offline selection in memory: they never change what the app installed on the
 * author's phone keeps offline, and nothing downloads.
 */
@Module
@TestInstallIn(components = [SingletonComponent::class], replaces = [OfflineControlsModule::class])
object TestOfflineModule {
    @Provides
    @Singleton
    fun offlineControls(): OfflineControls = MemoryOfflineControls()
}

class MemoryOfflineControls : OfflineControls {
    override val selection = MutableStateFlow(OfflineSelection())
    override val items = MutableStateFlow<List<OfflineItem>>(emptyList())

    override suspend fun keepTrack(track: PlayableTrack) =
        selection.update { it.copy(tracks = it.tracks + track) }

    override suspend fun dropTrack(id: SongId) =
        selection.update { s -> s.copy(tracks = s.tracks.filterNot { it.id == id }) }

    override suspend fun keepCollection(kind: CollectionKind, id: String, name: String) =
        selection.update {
            it.copy(collections = it.collections + OfflineCollection(kind, id, name))
        }

    override suspend fun dropCollection(kind: CollectionKind, id: String) = selection.update { s ->
        s.copy(collections = s.collections.filterNot { it.kind == kind && it.id == id })
    }

    override suspend fun syncSoon() = Unit
}
