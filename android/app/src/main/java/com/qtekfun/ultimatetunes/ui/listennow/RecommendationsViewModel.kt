// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.listennow

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.model.Recommendations
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import com.qtekfun.ultimatetunes.ui.model.toTile
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/** A "Because you played …" shelf; the UI builds its title from [seedTitle]. */
data class SeedShelf(val seedTitle: String, val tracks: List<TrackTile>)

/** An external-source shelf (e.g. ListenBrainz); [title] comes ready to show from the server. */
data class SourceShelf(val title: String, val tracks: List<TrackTile>)

/** The "Recommended for you" shelves, ready to show (empty shelves already dropped). */
data class RecommendationsContent(
    val recommendedForYou: List<TrackTile>,
    val becauseYouPlayed: List<SeedShelf>,
    val sources: List<SourceShelf>
) {
    val isEmpty: Boolean
        get() = recommendedForYou.isEmpty() && becauseYouPlayed.isEmpty() && sources.isEmpty()
}

/**
 * The "Recommended for you" section of Listen Now (RF-11), from `GET /ut/v1/recommendations`. It is
 * loaded apart from the cheap `GET /ut/v1/listen-now` because recommendations reach YouTube Music
 * (and are charged to the caller's bucket). It fails **gracefully**: an empty history or any error
 * leaves [state] null, so the section simply does not appear and never blocks Listen Now.
 */
@HiltViewModel
class RecommendationsViewModel @Inject constructor(private val api: TunesApi) : ViewModel() {
    private val mutableState = MutableStateFlow<RecommendationsContent?>(null)

    /** The shelves to show, or null while loading, when empty, or after a failure. */
    val state: StateFlow<RecommendationsContent?> = mutableState.asStateFlow()

    private var loading: Job? = null

    init {
        load()
    }

    /** Loads the recommendations again (with Listen Now's retry or refresh). */
    fun load() {
        if (loading?.isActive == true) return
        loading = viewModelScope.launch {
            val content = when (val result = api.recommendations(SHELF_LIMIT)) {
                is TunesResult.Success -> result.value.toContent()
                is TunesResult.Failure -> null
            }
            mutableState.value = content?.takeUnless { it.isEmpty }
        }
    }

    private fun Recommendations.toContent(): RecommendationsContent = RecommendationsContent(
        recommendedForYou = recommendedForYou.map { it.toTile(api) },
        becauseYouPlayed = becauseYouPlayed
            .filter { it.items.isNotEmpty() }
            .map { shelf -> SeedShelf(shelf.seed.title, shelf.items.map { it.toTile(api) }) },
        sources = shelves
            .filter { it.items.isNotEmpty() }
            .map { shelf -> SourceShelf(shelf.title, shelf.items.map { it.toTile(api) }) }
    )

    private companion object {
        /** Items asked per shelf (a shelf scrolls horizontally, so a handful is plenty). */
        const val SHELF_LIMIT = 20
    }
}
