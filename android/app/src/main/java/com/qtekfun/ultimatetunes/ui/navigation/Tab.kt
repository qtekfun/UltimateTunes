// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.navigation

import androidx.annotation.DrawableRes
import androidx.annotation.StringRes
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.ArtistId
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.ui.album.AlbumViewModel
import com.qtekfun.ultimatetunes.ui.artist.ArtistViewModel
import com.qtekfun.ultimatetunes.ui.playlists.PlaylistViewModel
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

    fun station(seed: SongId): String = "$route/station/${encode(seed.value)}"

    /** The Charts list inside this tab (opened from Listen Now). */
    val chartsPattern: String get() = "$route/charts"

    val charts: String get() = "$route/charts"

    /** Albums, artists and playlists open inside every tab, like stations. */
    val albumPattern: String get() = "$route/album/{${AlbumViewModel.ARG_ID}}"
    val artistPattern: String get() = "$route/artist/{${ArtistViewModel.ARG_ID}}"
    val playlistPattern: String get() = "$route/playlist/{${PlaylistViewModel.ARG_ID}}"

    fun album(id: AlbumId): String = "$route/album/${encode(id.value)}"

    fun artist(id: ArtistId): String = "$route/artist/${encode(id.value)}"

    fun playlist(id: PlaylistId): String = "$route/playlist/${encode(id.value)}"

    /** A Library page inside this tab. */
    fun page(page: LibraryPage): String = "$route/${page.route}"

    /** Test tag of the tab's bar item. */
    val testTag: String get() = "tab.$route"
}

/** Ids are opaque (`yt:…`, `ytalbum:…`): escaped so they stay one path segment. */
private fun encode(value: String): String = android.net.Uri.encode(value)
