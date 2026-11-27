// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.navigation

import androidx.compose.runtime.Immutable
import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.ArtistId
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.ui.model.TrackTile

/**
 * Where a screen can go and what it can start, passed as one value. Inside a tab every
 * destination opens in that tab, so the tab stays selected and Back returns to it.
 */
@Immutable
data class Navigator(
    val back: () -> Unit = {},
    val play: (List<TrackTile>, Int) -> Unit = { _, _ -> },
    val openAlbum: (AlbumId) -> Unit = {},
    val openArtist: (ArtistId) -> Unit = {},
    val openPlaylist: (PlaylistId) -> Unit = {},
    val openStation: (SongId) -> Unit = {},
    /** The Charts list (from Home). */
    val openCharts: () -> Unit = {},
    /** A page every tab can open ([LibraryPage]). */
    val openPage: (LibraryPage) -> Unit = {}
)

/** Favourites and downloads, plus Import and Settings: pages every tab can open. */
enum class LibraryPage(val route: String) {
    FAVOURITES("favourites"),
    DOWNLOADS("downloads"),
    IMPORT("import"),
    SETTINGS("settings")
}
