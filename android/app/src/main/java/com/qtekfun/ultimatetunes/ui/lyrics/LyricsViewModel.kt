// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.lyrics

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.model.Lyrics
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.model.loadStateOf
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/** One line of lyrics; [startMillis] (offset applied) only for synced lyrics. */
data class LyricLineUi(val text: String, val startMillis: Long?)

/** The lyrics of a song: synced lines (with times) or plain ones. */
data class LyricsContent(val lines: List<LyricLineUi>, val synced: Boolean)

/** The lyrics view's state; a ready null means the song has no lyrics. */
data class LyricsUiState(
    val songId: SongId? = null,
    val content: LoadState<LyricsContent?> = LoadState.Loading
)

/**
 * The lyrics of the song playing (RF-07, `getLyricsBySongId`), shown full screen in the player
 * with the active line highlighted. Synced lyrics are preferred over plain ones.
 */
@HiltViewModel
class LyricsViewModel @Inject constructor(private val api: TunesApi) : ViewModel() {
    private val mutableState = MutableStateFlow(LyricsUiState())
    val state: StateFlow<LyricsUiState> = mutableState.asStateFlow()

    private var loading: Job? = null

    /** Shows the lyrics of [songId], loading them unless they are already there. */
    fun show(songId: SongId) {
        val current = mutableState.value
        if (current.songId == songId && current.content !is LoadState.Failed) return
        load(songId)
    }

    /** Loads the current song's lyrics again (after an error). */
    fun retry() {
        mutableState.value.songId?.let(::load)
    }

    private fun load(songId: SongId) {
        loading?.cancel()
        mutableState.value = LyricsUiState(songId, LoadState.Loading)
        loading = viewModelScope.launch {
            val content = loadStateOf(api.lyrics(songId)) { list -> pick(list) }
            mutableState.value = LyricsUiState(songId, content)
        }
    }

    companion object {
        /** The synced lyrics if any, else the first plain ones; null when there are none. */
        fun pick(list: List<Lyrics>): LyricsContent? {
            val lyrics = list.firstOrNull { it.synced && it.line.isNotEmpty() }
                ?: list.firstOrNull { it.line.isNotEmpty() }
                ?: return null
            // OpenSubsonic: a positive offset shows the lyrics sooner.
            val offset = lyrics.offset?.toLong() ?: 0L
            return LyricsContent(
                lines = lyrics.line.map { line ->
                    LyricLineUi(
                        text = line.value,
                        startMillis = if (lyrics.synced) line.startMillis?.minus(offset) else null
                    )
                },
                synced = lyrics.synced
            )
        }

        /**
         * The index of the line sung at [positionMillis]: the last one that started, or -1 before
         * the first (and always for plain lyrics).
         */
        fun activeLine(lines: List<LyricLineUi>, positionMillis: Long): Int =
            lines.indexOfLast { it.startMillis != null && it.startMillis <= positionMillis }
    }
}
