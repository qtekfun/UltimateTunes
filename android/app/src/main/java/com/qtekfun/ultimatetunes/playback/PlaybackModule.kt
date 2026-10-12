// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.playback

import com.qtekfun.ultimatetunes.core.player.PlayerSettings
import com.qtekfun.ultimatetunes.core.player.PlayerSettingsSource
import com.qtekfun.ultimatetunes.ui.settings.PlaybackSettingsStore
import dagger.Binds
import dagger.Module
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import javax.inject.Inject
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

/** The player follows the settings the user picks in Settings (PLAN T13's store). */
class SettingsPlayerSource @Inject constructor(store: PlaybackSettingsStore) :
    PlayerSettingsSource {
    override val settings: Flow<PlayerSettings> = store.settings.map {
        PlayerSettings(
            cacheSizeMb = it.cacheSizeMb,
            offlineOnly = it.offlineOnly,
            downloadOnWifiOnly = it.downloadOnWifiOnly
        )
    }
}

@Module
@InstallIn(SingletonComponent::class)
interface PlaybackModule {
    @Binds
    fun playerSettings(source: SettingsPlayerSource): PlayerSettingsSource

    @Binds
    fun playerController(connection: PlaybackConnection): PlayerController

    @Binds
    fun offlineControls(controls: ManagerOfflineControls): OfflineControls
}
