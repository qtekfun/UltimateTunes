// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.library

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.model.AlbumListType
import com.qtekfun.ultimatetunes.ui.model.AlbumTile
import com.qtekfun.ultimatetunes.ui.model.LoadError
import com.qtekfun.ultimatetunes.ui.model.toLoadError
import com.qtekfun.ultimatetunes.ui.model.toTile
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** Library › Albums, loaded a page at a time. */
data class AlbumsUiState(
    val albums: List<AlbumTile> = emptyList(),
    val loading: Boolean = true,
    /** False once a page came back short: everything is loaded. */
    val hasMore: Boolean = true,
    val error: LoadError? = null
)

/**
 * Library › Albums: every album by name (`getAlbumList2?type=alphabeticalByName`), in pages of
 * [PAGE_SIZE] so a large library (SPEC §6: 50,000 tracks) opens quickly.
 */
@HiltViewModel
class AlbumsViewModel @Inject constructor(private val api: TunesApi) : ViewModel() {
    private val mutableState = MutableStateFlow(AlbumsUiState())
    val state: StateFlow<AlbumsUiState> = mutableState.asStateFlow()

    private var loading: Job? = null

    init {
        loadMore()
    }

    /** Loads the next page (also the retry after an error); does nothing when all are loaded. */
    fun loadMore() {
        if (loading?.isActive == true || !mutableState.value.hasMore) return
        mutableState.update { it.copy(loading = true, error = null) }
        loading = viewModelScope.launch {
            val offset = mutableState.value.albums.size
            val result = api.albumList(
                AlbumListType.ALPHABETICAL_BY_NAME,
                size = PAGE_SIZE,
                offset = offset
            )
            mutableState.update { state ->
                when (result) {
                    is TunesResult.Success -> state.copy(
                        albums = state.albums + result.value.map { it.toTile(api) },
                        loading = false,
                        hasMore = result.value.size == PAGE_SIZE
                    )

                    is TunesResult.Failure -> state.copy(
                        loading = false,
                        error = result.toLoadError()
                    )
                }
            }
        }
    }

    companion object {
        const val PAGE_SIZE = 60
    }
}
