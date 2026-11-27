// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.playlists

import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow

/** Tells open screens that songs were added to a playlist from somewhere else. */
@Singleton
class PlaylistChanges @Inject constructor() {
    private val mutableChanged = MutableSharedFlow<PlaylistId>(extraBufferCapacity = BUFFER)
    val changed: SharedFlow<PlaylistId> = mutableChanged.asSharedFlow()

    fun changed(id: PlaylistId) {
        mutableChanged.tryEmit(id)
    }

    private companion object {
        const val BUFFER = 8
    }
}
