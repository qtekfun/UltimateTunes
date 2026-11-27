// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.library

import com.qtekfun.ultimatetunes.core.api.model.Album
import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.Artist
import com.qtekfun.ultimatetunes.core.api.model.ArtistId
import com.qtekfun.ultimatetunes.core.api.model.CoverArtId
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import com.qtekfun.ultimatetunes.core.api.model.ReplayGain
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.api.model.Starred
import java.time.Duration
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Test

class LibraryRepositoryTest {
    private val harness = CatalogHarness()
    private val remote = harness.remote
    private val repository = harness.repository

    private val main = artist("ar1", "Ñandú")
    private val guest = artist("ar2", "Zoë")
    private val gain = ReplayGain(trackGain = -7.5, trackPeak = 0.9)
    private val old = NOW.minus(Duration.ofDays(30))

    private val library = listOf(
        song("s1", "Árbol", album = "al1", track = 2, created = old, played = old, plays = 5),
        song("s2", "zeta", album = "al1", track = 1, created = NOW, played = NOW, plays = 1)
            .copy(replayGain = gain, coverArt = CoverArtId("al-al1")),
        song("s3", "Bosque", album = "al1", disc = 2, track = 1, by = guest, albumBy = main),
        song("s4", "Casa", album = "al2", year = 2024, created = old),
        song("s5", "Loose", album = null, by = guest, year = null, created = old)
    )

    @AfterEach
    fun close() = harness.close()

    private fun sync() = runBlocking {
        remote.songs = library
        assertEquals(CatalogSyncResult.Synced, harness.syncer.sync())
    }

    @Test
    fun `songs are sorted without case or accents and keep what playing them needs`() =
        runBlocking {
            sync()

            val songs = repository.songs().first()

            assertEquals(listOf("Árbol", "Bosque", "Casa", "Loose", "zeta"), songs.map { it.title })
            val zeta = songs.last()
            assertEquals(gain, zeta.replayGain)
            assertEquals(CoverArtId("al-al1"), zeta.coverArt)
            assertEquals(main.id, zeta.artistId)
            assertEquals(main.name, zeta.displayAlbumArtist)
            assertEquals(100, zeta.duration)
            assertEquals(NOW, zeta.played)
        }

    @Test
    fun `albums and artists come from the songs`() = runBlocking {
        sync()

        val album = repository.albums().first().first()
        assertEquals("Album al1", album.name)
        assertEquals("Ñandú", album.artist)
        assertEquals(3, album.songCount)
        assertEquals(300, album.duration)
        assertEquals(6L, album.playCount)
        assertEquals(old, album.created)
        assertEquals(NOW, album.played)
        assertEquals(CoverArtId("al-al1"), album.coverArt)

        val artists = repository.artists().first()
        assertEquals(listOf("Ñandú", "Zoë"), artists.map { it.name })
        assertEquals(listOf(2, 0), artists.map { it.albumCount })
    }

    @Test
    fun `an album has its songs by disc and track, an artist its albums newest first`() =
        runBlocking {
            sync()

            val album = repository.album(AlbumId("al1")).first()!!
            assertEquals(listOf("s2", "s1", "s3"), album.song.map { it.id.value })

            val artist = repository.artist(main.id).first()!!
            assertEquals(listOf("al2", "al1"), artist.album.map { it.id.value })
            assertEquals(4, repository.artistSongs(main.id).first().size)
            assertEquals(
                listOf("s3", "s5"),
                repository.artistSongs(guest.id).first().map { it.id.value }
            )

            assertNull(repository.album(AlbumId("none")).first())
            assertNull(repository.artist(ArtistId("none")).first())
            assertNull(repository.playlist(PlaylistId("none")).first())
        }

    @Test
    fun `recently added, recently played and most played`() = runBlocking {
        sync()

        assertEquals(
            listOf("s3", "s2"),
            repository.recentlyAddedSongs(2).first().map { it.id.value }
        )
        assertEquals(
            listOf("al2", "al1"),
            repository.recentlyAddedAlbums(5).first().map { it.id.value }.sortedDescending()
        )
        assertEquals(
            listOf("s2", "s1"),
            repository.recentlyPlayedSongs(5).first().map { it.id.value }
        )
        assertEquals(listOf("s1", "s2"), repository.mostPlayedSongs(5).first().map { it.id.value })
        assertEquals(
            listOf("al1"),
            repository.recentlyPlayedAlbums(5).first().map { it.id.value }
        )
    }

    @Test
    fun `favourites keep the server's order, those outside the library too`() = runBlocking {
        val pending = song("yt:Qx7Lm2pZ0aB", "Soon", album = null, played = NOW, plays = 9)
        remote.starred = Starred(
            artist = listOf(Artist(guest.id, guest.name, starred = NOW)),
            album = listOf(
                Album(AlbumId("al2"), "Album al2", starred = NOW),
                Album(AlbumId("al9"), "Elsewhere", artist = "X")
            ),
            song = listOf(pending.copy(starred = NOW), library[0].copy(starred = old))
        )
        sync()

        val songs = repository.favouriteSongs().first()
        assertEquals(listOf(pending.id, SongId("s1")), songs.map { it.id })
        assertEquals(listOf(NOW, old), songs.map { it.starred })
        assertEquals(
            listOf("al2", "al9"),
            repository.favouriteAlbums().first().map { it.id.value }
        )
        assertEquals(listOf(guest.id), repository.favouriteArtists().first().map { it.id })
        // Only the library is listed as such.
        assertEquals(5, repository.songs().first().size)
        assertEquals(2, repository.albums().first().size)
        assertEquals(
            listOf("s2", "s1"),
            repository.recentlyPlayedSongs(5).first().map {
                it.id.value
            }
        )
    }

    @Test
    fun `a favourite artist with no songs is a favourite but not listed`() = runBlocking {
        remote.starred = Starred(artist = listOf(Artist(ArtistId("ar9"), "Gone")))
        sync()

        assertEquals(listOf("Gone"), repository.favouriteArtists().first().map { it.name })
        assertEquals(2, repository.artists().first().size)
    }

    @Test
    fun `playlists keep their order and repeated songs, and give ids to match downloads`() =
        runBlocking {
            val twice = listOf(library[3], library[0], library[3])
            remote.playlists = listOf(
                playlist("p1", "Zulu", twice),
                playlist("p2", "Empty", emptyList()).copy(readonly = true, owner = "bob")
            )
            sync()

            assertEquals(listOf("Zulu", "Empty"), repository.playlists().first().map { it.name })
            val detail = repository.playlist(PlaylistId("p1")).first()!!
            assertEquals(listOf("s4", "s1", "s4"), detail.entry.map { it.id.value })
            assertEquals(true, repository.playlists().first().last().readonly)
            assertEquals(
                mapOf(PlaylistId("p1") to listOf(SongId("s4"), SongId("s1"), SongId("s4"))),
                repository.playlistSongIds().first()
            )
            val ref = repository.songRefs().first().single { it.id == SongId("s3") }
            assertEquals(SongRef(SongId("s3"), AlbumId("al1"), guest.id, main.id), ref)
        }
}
