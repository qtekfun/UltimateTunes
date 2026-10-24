// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.preview

import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.ApiKeyId
import com.qtekfun.ultimatetunes.core.api.model.ArtistId
import com.qtekfun.ultimatetunes.core.api.model.ImportId
import com.qtekfun.ultimatetunes.core.api.model.ImportItemState
import com.qtekfun.ultimatetunes.core.api.model.ImportSource
import com.qtekfun.ultimatetunes.core.api.model.ImportState
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.ui.album.AlbumContent
import com.qtekfun.ultimatetunes.ui.artist.ArtistContent
import com.qtekfun.ultimatetunes.ui.charts.ChartsContent
import com.qtekfun.ultimatetunes.ui.imports.ImportProgress
import com.qtekfun.ultimatetunes.ui.imports.ImportRow
import com.qtekfun.ultimatetunes.ui.listennow.ListenNowContent
import com.qtekfun.ultimatetunes.ui.listennow.RecommendationsContent
import com.qtekfun.ultimatetunes.ui.listennow.SeedShelf
import com.qtekfun.ultimatetunes.ui.listennow.SourceShelf
import com.qtekfun.ultimatetunes.ui.model.AlbumTile
import com.qtekfun.ultimatetunes.ui.model.ArtistTile
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.model.PlaylistTile
import com.qtekfun.ultimatetunes.ui.model.StationTile
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import com.qtekfun.ultimatetunes.ui.playlists.PlaylistContent
import com.qtekfun.ultimatetunes.ui.radio.RadioContent
import com.qtekfun.ultimatetunes.ui.radio.StationContent
import com.qtekfun.ultimatetunes.ui.search.SearchContent
import com.qtekfun.ultimatetunes.ui.settings.KeyRow
import com.qtekfun.ultimatetunes.ui.settings.ServerDetails
import com.qtekfun.ultimatetunes.ui.settings.SettingsUiState
import java.time.Instant

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

    val recommendations = RecommendationsContent(
        recommendedForYou = tracks.take(n = 4),
        becauseYouPlayed = listOf(SeedShelf("Lighthouse Keeper", tracks.drop(n = 1).take(n = 3))),
        sources = listOf(
            SourceShelf("Popular on ListenBrainz · The Paper Lanterns", tracks.takeLast(n = 3))
        )
    )

    val charts = ChartsContent(country = "ES", tracks = tracks)

    val radio = RadioContent(
        featured = stations.take(1),
        fromSongs = tracks.take(n = 3).map { StationTile(it.id, it.title, it.artist, null) }
    )

    val station = StationContent(seed = tracks.first(), upNext = tracks.drop(1))

    private val lanterns = ArtistTile(
        ArtistId("preview-artist-1"),
        "The Paper Lanterns",
        coverUrl = null,
        isExternal = false
    )

    val search = SearchContent(
        artists = listOf(
            lanterns,
            ArtistTile(ArtistId("ytartist:preview"), "Copper Coast", null, isExternal = true)
        ),
        albums = listOf(
            albums.first(),
            AlbumTile(
                AlbumId("ytalbum:preview"),
                "Lanterns at Dusk",
                "The Paper Lanterns",
                null,
                isExternal = true
            )
        ),
        tracks = tracks
    )

    val album = AlbumContent(
        album = albums.first(),
        artistId = lanterns.id,
        year = 2023,
        genre = "Indie Pop",
        durationSec = 2287,
        tracks = tracks.take(2).mapIndexed { i, t -> t.copy(trackNumber = i + 1) },
        isFavourite = true
    )

    val artist = ArtistContent(artist = lanterns, albums = albums.take(n = 3))

    val playlists = listOf(
        PlaylistTile(
            PlaylistId("preview-playlist-1"),
            "Sunday Morning",
            songCount = 3,
            durationSec = 663,
            coverUrl = null
        ),
        PlaylistTile(
            PlaylistId("preview-playlist-2"),
            "Road Trip",
            songCount = 42,
            durationSec = 9_480,
            coverUrl = null
        )
    )

    val playlist = PlaylistContent(
        playlist = playlists.first(),
        comment = "Slow songs for slow mornings",
        tracks = tracks.take(n = 3),
        readonly = false
    )

    val importDone = ImportProgress(
        id = ImportId("preview-import-1"),
        name = "Road Trip",
        source = ImportSource.YTMUSIC,
        state = ImportState.DONE,
        progress = 1.0,
        total = 3,
        matched = 2,
        notFound = 1,
        playlistId = playlists[1].id,
        rows = listOf(
            ImportRow(
                position = 0,
                title = "Lighthouse Keeper",
                artist = "The Paper Lanterns",
                state = ImportItemState.MATCHED,
                match = tracks.first()
            ),
            ImportRow(
                position = 1,
                title = "Copper Fields",
                artist = "Marisol Vega",
                state = ImportItemState.MATCHED,
                match = tracks.last()
            ),
            ImportRow(
                position = 2,
                title = "Untitled Demo 4",
                artist = "Northbound Static",
                state = ImportItemState.NOT_FOUND,
                match = null
            )
        )
    )

    val settings = SettingsUiState(
        server = LoadState.Ready(
            ServerDetails(
                address = "https://music.example.net/",
                name = "UltimateTunes",
                version = "0.1.0",
                username = "alice",
                isAdmin = false
            )
        ),
        keys = LoadState.Ready(
            listOf(
                KeyRow(
                    ApiKeyId("preview-key-1"),
                    "Phone",
                    "utk_EXAMPLEe",
                    Instant.parse("2026-10-01T17:20:00Z"),
                    Instant.parse("2026-10-12T08:15:30Z"),
                    current = true
                ),
                KeyRow(
                    ApiKeyId("preview-key-2"),
                    "Tablet",
                    "utk_EXAMPLEf",
                    Instant.parse("2026-09-14T09:02:11Z"),
                    null,
                    current = false
                )
            )
        )
    )
}
