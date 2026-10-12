// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.preview

import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.ui.listennow.ListenNowContent
import com.qtekfun.ultimatetunes.ui.model.AlbumTile
import com.qtekfun.ultimatetunes.ui.model.StationTile
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import com.qtekfun.ultimatetunes.ui.radio.RadioContent
import com.qtekfun.ultimatetunes.ui.radio.StationContent

/**
 * Invented artists, albums and songs for previews and screenshots (CLAUDE.md: never real data).
 * No cover URLs: the artwork shows its gradient placeholder.
 */
internal object PreviewData {
    private fun album(n: Int, title: String, artist: String) =
        AlbumTile(AlbumId("preview-album-$n"), title, artist, coverUrl = null, isExternal = false)

    private fun track(
        n: Int,
        title: String,
        artist: String,
        album: String,
        external: Boolean = false
    ) = TrackTile(
        id = SongId("preview-song-$n"),
        title = title,
        artist = artist,
        album = album,
        durationSec = 180 + n * 17,
        coverUrl = null,
        isExternal = external
    )

    val albums = listOf(
        album(n = 1, title = "Harbour Lights", artist = "The Paper Lanterns"),
        album(n = 2, title = "Salt & Ember", artist = "Marisol Vega"),
        album(n = 3, title = "Low Orbit", artist = "Northbound Static"),
        album(n = 4, title = "Glass Orchard", artist = "Wren & the Quiet"),
        album(n = 5, title = "Midnight Ferry", artist = "Ola Brenner")
    )

    val tracks = listOf(
        track(
            n = 1,
            title = "Lighthouse Keeper",
            artist = "The Paper Lanterns",
            album = "Harbour Lights"
        ),
        track(n = 2, title = "Tidewater", artist = "The Paper Lanterns", album = "Harbour Lights"),
        track(n = 3, title = "Brasas", artist = "Marisol Vega", album = "Salt & Ember"),
        track(
            n = 4,
            title = "Copper Fields",
            artist = "Marisol Vega",
            album = "Copper Fields",
            external = true
        ),
        track(
            n = 5,
            title = "Paper Moons (Live)",
            artist = "The Paper Lanterns",
            album = "Lanterns at Dusk",
            external = true
        )
    )

    val stations = listOf(
        StationTile(
            SongId("preview-song-1"),
            "Lighthouse Keeper Radio",
            "The Paper Lanterns",
            null
        ),
        StationTile(SongId("preview-song-3"), "Brasas Radio", "Marisol Vega", null)
    )

    val listenNow = ListenNowContent(
        recentlyPlayed = albums.take(n = 3),
        recentlyAdded = albums,
        mostPlayed = tracks.take(n = 3),
        stations = stations
    )

    val radio = RadioContent(
        featured = stations.take(1),
        fromSongs = tracks.take(n = 3).map { StationTile(it.id, it.title, it.artist, null) }
    )

    val station = StationContent(seed = tracks.first(), upNext = tracks.drop(1))
}
