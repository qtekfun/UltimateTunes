// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.navigation

import androidx.annotation.DrawableRes
import androidx.annotation.StringRes
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.ui.radio.StationViewModel

/** The four tabs of the bottom bar (SPEC §5), each a nested navigation graph. */
enum class Tab(val route: String, @StringRes val label: Int, @DrawableRes val icon: Int) {
    LISTEN_NOW("listenNow", R.string.tab_listen_now, R.drawable.ic_listen_now),
    RADIO("radio", R.string.tab_radio, R.drawable.ic_radio),
    LIBRARY("library", R.string.tab_library, R.drawable.ic_library),
    SEARCH("search", R.string.tab_search, R.drawable.ic_search);

    /** The tab's first screen. */
    val home: String get() = "$route/home"

    /** A station inside this tab, so the tab stays selected and back returns to it. */
    val stationPattern: String get() = "$route/station/{${StationViewModel.ARG_SEED}}"

    fun station(seed: SongId): String = "$route/station/${android.net.Uri.encode(seed.value)}"

    /** Test tag of the tab's bar item. */
    val testTag: String get() = "tab.$route"
}
