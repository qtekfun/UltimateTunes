// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.library

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.model.AlbumListType
import com.qtekfun.ultimatetunes.ui.model.AlbumTile
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.model.loadStateOf
import com.qtekfun.ultimatetunes.ui.model.toTile
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * The Library tab (RF-11): its menu (playlists, artists, albums, favourites, downloads) is fixed;
 * below it, the albums added last (`getAlbumList2?type=newest`).
 */
@HiltViewModel
class LibraryViewModel @Inject constructor(private val api: TunesApi) : ViewModel() {
    private val mutableState = MutableStateFlow<LoadState<List<AlbumTile>>>(LoadState.Loading)
    val recentlyAdded: StateFlow<LoadState<List<AlbumTile>>> = mutableState.asStateFlow()

    private var loading: Job? = null

    init {
        load()
    }

    fun load() {
        if (loading?.isActive == true) return
        if (mutableState.value !is LoadState.Ready) mutableState.value = LoadState.Loading
        loading = viewModelScope.launch {
            mutableState.value =
                loadStateOf(api.albumList(AlbumListType.NEWEST, size = RECENT_COUNT)) { albums ->
                    albums.map { it.toTile(api) }
                }
        }
    }

    companion object {
        /** Albums in "Recently Added". */
        const val RECENT_COUNT = 12
    }
}
