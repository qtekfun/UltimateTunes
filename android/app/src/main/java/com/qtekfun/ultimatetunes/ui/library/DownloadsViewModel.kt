// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.library

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn

/** Library › Downloads: the songs kept for offline listening (RF-12), as [OfflineLibrary] lists them. */
@HiltViewModel
class DownloadsViewModel @Inject constructor(offline: OfflineLibrary) : ViewModel() {
    val state: StateFlow<LoadState<List<TrackTile>>> = offline.downloads
        .map<List<TrackTile>, LoadState<List<TrackTile>>> { LoadState.Ready(it) }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(STOP_TIMEOUT_MS), LoadState.Loading)

    private companion object {
        const val STOP_TIMEOUT_MS = 5_000L
    }
}
