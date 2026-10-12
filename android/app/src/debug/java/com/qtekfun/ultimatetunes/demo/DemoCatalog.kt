// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.demo

import com.qtekfun.ultimatetunes.core.api.model.Album
import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.AlbumItem
import com.qtekfun.ultimatetunes.core.api.model.Artist
import com.qtekfun.ultimatetunes.core.api.model.ArtistId
import com.qtekfun.ultimatetunes.core.api.model.ArtistItem
import com.qtekfun.ultimatetunes.core.api.model.ArtistRef
import com.qtekfun.ultimatetunes.core.api.model.CoverArtId
import com.qtekfun.ultimatetunes.core.api.model.Genre
import com.qtekfun.ultimatetunes.core.api.model.LibraryState
import com.qtekfun.ultimatetunes.core.api.model.LyricLine
import com.qtekfun.ultimatetunes.core.api.model.Lyrics
import com.qtekfun.ultimatetunes.core.api.model.RadioStation
import com.qtekfun.ultimatetunes.core.api.model.Song
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.api.model.TrackItem
import java.time.Instant

/*
 * The demo library: invented artists, albums and songs (no real names, CLAUDE.md), with covers
 * drawn by DemoArtwork from the names. Debug builds only.
 */

/** One invented album: title, year, genre and its songs (title, seconds). */
private class AlbumSeed(
    val title: String,
    val year: Int,
    val genre: String,
    val songs: List<Pair<String, Int>>
)

private class ArtistSeed(val name: String, val albums: List<AlbumSeed>)

@Suppress("MagicNumber") // Invented durations and years.
private val SEEDS = listOf(
    ArtistSeed(
        "Copper Fern",
        listOf(
            AlbumSeed(
                "Lanterns in the Rye",
                2024,
                "Folk",
                listOf(
                    "Lanterns in the Rye" to 214,
                    "Kettle Smoke" to 187,
                    "The Long Field" to 241,
                    "Barn Owl Waltz" to 198,
                    "Northbound Letters" to 226,
                    "Ember and Thread" to 205,
                    "Quiet Acre" to 263
                )
            ),
            AlbumSeed(
                "Small Hours",
                2021,
                "Folk",
                listOf(
                    "Small Hours" to 201,
                    "Wool Coat Weather" to 176,
                    "Tin Roof Rain" to 219,
                    "A Map of Sparrows" to 232,
                    "Lamplight Promise" to 194,
                    "Woodsmoke" to 248
                )
            )
        )
    ),
    ArtistSeed(
        "Nova Kestrel",
        listOf(
            AlbumSeed(
                "Neon Tide",
                2025,
                "Synth-pop",
                listOf(
                    "Neon Tide" to 203,
                    "Afterglow Avenue" to 191,
                    "Signal Fire" to 224,
                    "Chrome Hearts Club" to 187,
                    "Parallel Summer" to 236,
                    "Satellite Kiss" to 199,
                    "Midnight Arcade" to 245,
                    "Pulse in Pastel" to 212
                )
            ),
            AlbumSeed(
                "Glass Satellites",
                2022,
                "Synth-pop",
                listOf(
                    "Glass Satellites" to 218,
                    "Orbit of You" to 197,
                    "Static Valentine" to 183,
                    "Low Earth Love" to 229,
                    "Telemetry" to 241
                )
            )
        )
    ),
    ArtistSeed(
        "The Midnight Orchard",
        listOf(
            AlbumSeed(
                "Rust & Honey",
                2023,
                "Rock",
                listOf(
                    "Rust & Honey" to 232,
                    "Gravel Road Gospel" to 254,
                    "Burnt Sienna" to 207,
                    "Pickup Truck Halo" to 219,
                    "Thunder in the Pantry" to 196,
                    "Cider Moon" to 271,
                    "Last Light at the Mill" to 302
                )
            )
        )
    ),
    ArtistSeed(
        "Marisol Tideway",
        listOf(
            AlbumSeed(
                "Paper Boats",
                2024,
                "Singer-songwriter",
                listOf(
                    "Paper Boats" to 208,
                    "Harbour Glass" to 189,
                    "Seven Small Stones" to 223,
                    "The Lighthouse Keeps Score" to 241,
                    "Undertow" to 197,
                    "Salt in the Sugar Jar" to 214
                )
            )
        )
    ),
    ArtistSeed(
        "Ivo Brandt Trio",
        listOf(
            AlbumSeed(
                "Blue Hour Sessions",
                2020,
                "Jazz",
                listOf(
                    "Blue Hour" to 312,
                    "Walking the Bassline Home" to 284,
                    "Rainy Tram" to 266,
                    "Cobblestone Swing" to 241,
                    "Velvet Brushes" to 333,
                    "Nocturne for a Doorbell" to 298
                )
            ),
            AlbumSeed(
                "Late Train to Lisbon",
                2023,
                "Jazz",
                listOf(
                    "Late Train" to 327,
                    "Platform Nine Blues" to 289,
                    "Coffee with Ghosts" to 254,
                    "Azulejo" to 276,
                    "The Conductor Sleeps" to 311
                )
            )
        )
    ),
    ArtistSeed(
        "Saltwater Static",
        listOf(
            AlbumSeed(
                "Low Frequency Bloom",
                2025,
                "Electronic",
                listOf(
                    "Low Frequency Bloom" to 268,
                    "Tidal Grid" to 301,
                    "Kelp Forest Rave" to 243,
                    "Deep Blue Modem" to 287,
                    "Bioluminescence" to 322,
                    "Pressure Drop" to 256,
                    "Moon Pool" to 299
                )
            )
        )
    ),
    ArtistSeed(
        "Juniper & Vale",
        listOf(
            AlbumSeed(
                "Soft Weather",
                2022,
                "Dream pop",
                listOf(
                    "Soft Weather" to 229,
                    "Cloudberry" to 204,
                    "Slow Motion Snow" to 247,
                    "Hush Harbour" to 213,
                    "Pillow Fort Kingdom" to 192,
                    "Fog Lights" to 238
                )
            )
        )
    ),
    ArtistSeed(
        "Los Faroles del Sur",
        listOf(
            AlbumSeed(
                "Luz de Agosto",
                2024,
                "Pop",
                listOf(
                    "Luz de Agosto" to 206,
                    "Bailando en la Azotea" to 194,
                    "Sal y Limón" to 181,
                    "Verbena" to 217,
                    "Mareas" to 229,
                    "Últimos Ferrys" to 242
                )
            )
        )
    )
)

/** Songs on YouTube Music "not in the library yet", shown by search (also invented). */
@Suppress("MagicNumber")
private val EXTERNAL = listOf(
    Triple("Paper Moon Parade", "Copper Fern", 219),
    Triple("Neon Tide (Acoustic)", "Nova Kestrel", 207),
    Triple("Blue Hour (Live at the Pier)", "Ivo Brandt Trio", 356),
    Triple("Undertow (Night Version)", "Marisol Tideway", 231)
)

/** The demo library as API models, built once. */
@Suppress("MagicNumber")
internal object DemoCatalog {
    /** A fixed point in time for "created" dates. */
    private val CREATED: Instant = Instant.parse("2026-09-01T10:00:00Z")

    private fun uuid(kind: Int, n: Int): String = "0199e0de-%04x-7000-8000-%012x".format(kind, n)

    val artists: List<Artist>
    val albums: List<Album>
    val songs: List<Song>
    val externalSongs: List<Song>

    /** Cover ids and the text their artwork shows. */
    val coverLabels: Map<String, String>

    init {
        val artistList = mutableListOf<Artist>()
        val albumList = mutableListOf<Album>()
        val songList = mutableListOf<Song>()
        val labels = mutableMapOf<String, String>()
        var albumIndex = 0
        var songIndex = 0
        SEEDS.forEachIndexed { artistIndex, seed ->
            val artistId = ArtistId(uuid(1, artistIndex + 1))
            val artistCover = CoverArtId("ar-${artistId.value}")
            labels[artistCover.value] = seed.name
            val artistRef = ArtistRef(artistId, seed.name)
            val artistAlbums = seed.albums.map { albumSeed ->
                albumIndex++
                val albumId = AlbumId(uuid(2, albumIndex))
                val cover = CoverArtId("al-${albumId.value}")
                labels[cover.value] = albumSeed.title
                val albumSongs = albumSeed.songs.mapIndexed { i, (title, seconds) ->
                    songIndex++
                    Song(
                        id = SongId(uuid(3, songIndex)),
                        title = title,
                        parent = albumId.value,
                        album = albumSeed.title,
                        artist = seed.name,
                        track = i + 1,
                        year = albumSeed.year,
                        genre = albumSeed.genre,
                        coverArt = cover,
                        size = seconds * 20_000L,
                        contentType = "audio/ogg",
                        suffix = "opus",
                        duration = seconds,
                        bitRate = 160,
                        playCount = ((songIndex * 37) % 50).toLong(),
                        discNumber = 1,
                        created = CREATED.minusSeconds(albumIndex * 86_400L),
                        albumId = albumId,
                        artistId = artistId,
                        genres = listOf(Genre(albumSeed.genre)),
                        artists = listOf(artistRef),
                        displayArtist = seed.name,
                        albumArtists = listOf(artistRef),
                        displayAlbumArtist = seed.name
                    )
                }
                songList += albumSongs
                Album(
                    id = albumId,
                    name = albumSeed.title,
                    artist = seed.name,
                    artistId = artistId,
                    coverArt = cover,
                    songCount = albumSongs.size,
                    duration = albumSongs.sumOf { it.duration ?: 0 },
                    created = CREATED.minusSeconds(albumIndex * 86_400L),
                    year = albumSeed.year,
                    genre = albumSeed.genre,
                    genres = listOf(Genre(albumSeed.genre)),
                    artists = listOf(artistRef),
                    displayArtist = seed.name,
                    song = albumSongs
                )
            }
            albumList += artistAlbums
            artistList += Artist(
                id = artistId,
                name = seed.name,
                coverArt = artistCover,
                albumCount = artistAlbums.size,
                sortName = seed.name.removePrefix("The ").removePrefix("Los "),
                album = artistAlbums.map { it.copy(song = emptyList()) }
            )
        }
        externalSongs = EXTERNAL.mapIndexed { i, (title, artist, seconds) ->
            val id = SongId("yt:demoTrack0${i + 1}")
            labels[id.value] = title
            Song(
                id = id,
                title = title,
                artist = artist,
                coverArt = CoverArtId(id.value),
                duration = seconds,
                displayArtist = artist
            )
        }
        artists = artistList
        albums = albumList
        songs = songList
        coverLabels = labels
    }

    fun artist(id: String): Artist? = artists.firstOrNull { it.id.value == id }

    fun album(id: String): Album? = albums.firstOrNull { it.id.value == id }

    fun song(id: String): Song? =
        songs.firstOrNull { it.id.value == id } ?: externalSongs.firstOrNull { it.id.value == id }

    private fun albumNamed(title: String): Album = albums.first { it.name == title }

    private fun songNamed(title: String): Song = songs.first { it.title == title }

    val recentlyPlayed: List<Album> by lazy {
        listOf(
            "Neon Tide",
            "Lanterns in the Rye",
            "Blue Hour Sessions",
            "Luz de Agosto",
            "Soft Weather",
            "Rust & Honey"
        ).map(::albumNamed)
    }

    val recentlyAdded: List<Album> by lazy {
        listOf(
            "Low Frequency Bloom",
            "Paper Boats",
            "Late Train to Lisbon",
            "Glass Satellites",
            "Small Hours"
        ).map(::albumNamed)
    }

    val mostPlayed: List<Song> by lazy {
        listOf(
            "Afterglow Avenue",
            "Kettle Smoke",
            "Bailando en la Azotea",
            "Cloudberry",
            "Walking the Bassline Home",
            "Tidal Grid",
            "Gravel Road Gospel",
            "Harbour Glass",
            "Orbit of You",
            "Tin Roof Rain"
        ).map(::songNamed)
    }

    val stations: List<RadioStation> by lazy {
        listOf(
            Triple("Neon Tide", "Nova Kestrel Radio", "Nova Kestrel, Saltwater Static and more"),
            Triple("Kettle Smoke", "Copper Fern Radio", "Copper Fern, Juniper & Vale and more"),
            Triple("Blue Hour", "Late-Night Jazz", "Ivo Brandt Trio and more"),
            Triple("Verbena", "Sunny Afternoons", "Los Faroles del Sur, Marisol Tideway and more")
        ).map { (seed, title, subtitle) ->
            val song = songNamed(seed)
            RadioStation(song.id, title, subtitle, checkNotNull(song.coverArt))
        }
    }

    /** Invented lyrics for [song], synced line by line. */
    fun lyrics(song: Song): Lyrics {
        val verses = listOf(
            "Here comes the ${song.title.lowercase()}",
            "Humming low beneath the streetlights",
            "Every window keeps a little tune",
            "We were dancing in the kitchen",
            "Counting stars we never named",
            "Oh, the ${song.title.lowercase()}",
            "Carry me home, carry me home",
            "Till the morning finds us singing",
            "",
            "Here comes the ${song.title.lowercase()}",
            "Carry me home"
        )
        return Lyrics(
            lang = "en",
            synced = true,
            line = verses.mapIndexed { i, text -> LyricLine(text, (i * 6_500 + 1_000).toDouble()) },
            displayArtist = song.displayArtist,
            displayTitle = song.title
        )
    }

    fun Song.toTrackItem(): TrackItem = TrackItem(
        id = id,
        title = title,
        artist = artist.orEmpty(),
        artistId = artistId,
        album = album,
        albumId = albumId,
        durationSec = duration,
        year = year,
        coverArt = coverArt ?: CoverArtId(id.value),
        isExternal = isExternal,
        libraryState = if (isExternal) null else LibraryState.READY
    )

    fun Album.toAlbumItem(): AlbumItem = AlbumItem(
        id = id,
        name = name,
        artist = artist.orEmpty(),
        artistId = artistId,
        year = year,
        songCount = songCount,
        coverArt = coverArt ?: CoverArtId("al-${id.value}"),
        isExternal = isExternal
    )

    fun Artist.toArtistItem(): ArtistItem = ArtistItem(
        id = id,
        name = name,
        coverArt = coverArt ?: CoverArtId("ar-${id.value}"),
        isExternal = isExternal
    )
}
