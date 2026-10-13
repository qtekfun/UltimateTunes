// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.charts

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import com.qtekfun.ultimatetunes.ui.model.loadStateOf
import com.qtekfun.ultimatetunes.ui.model.toTile
import dagger.hilt.android.lifecycle.HiltViewModel
import java.util.Locale
import javax.inject.Inject
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/** A country's chart songs, ready to show. [country] is what the server answered (`ZZ` global). */
data class ChartsContent(val country: String, val tracks: List<TrackTile>) {
    val isEmpty: Boolean get() = tracks.isEmpty()
}

/**
 * The Charts list (RF-11), from `GET /ut/v1/charts`. The country defaults to the device region
 * ([defaultChartsCountry]); when there is none the server's configured default is used.
 */
@HiltViewModel
class ChartsViewModel @Inject constructor(private val api: TunesApi) : ViewModel() {
    private val mutableState = MutableStateFlow<LoadState<ChartsContent>>(LoadState.Loading)
    val state: StateFlow<LoadState<ChartsContent>> = mutableState.asStateFlow()

    private var loading: Job? = null

    init {
        load()
    }

    fun load() {
        if (loading?.isActive == true) return
        if (mutableState.value !is LoadState.Ready) mutableState.value = LoadState.Loading
        loading = viewModelScope.launch {
            mutableState.value =
                loadStateOf(api.charts(country = defaultChartsCountry())) { charts ->
                    ChartsContent(charts.country, charts.items.map { it.toTile(api) })
                }
        }
    }
}

/**
 * The device's region as an ISO 3166-1 alpha-2 country code for the charts, or null to let the
 * server use its configured default (`UT_CHARTS_COUNTRY`). A locale with no two-letter region
 * (e.g. a UN M.49 area code like `419`) yields null rather than an invalid code.
 */
internal fun defaultChartsCountry(locale: Locale = Locale.getDefault()): String? =
    locale.country.takeIf { it.length == 2 }?.uppercase(Locale.ROOT)
