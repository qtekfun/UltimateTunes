// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.offline

import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.model.Album
import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.Song
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.player.PlayableTrack
import com.qtekfun.ultimatetunes.core.player.PlayerSettings
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.every
import io.mockk.mockk
import java.io.IOException
import java.time.Instant
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import okhttp3.HttpUrl.Companion.toHttpUrl
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

private const val MB = 1024L * 1024

private fun song(
    n: Int,
    mb: Long? = 1,
    plays: Long? = null,
    starred: Boolean = false,
    createdDay: Int = 1,
    bitRate: Int? = null,
    seconds: Int? = null
) = Song(
    id = libId(n),
    title = "Song $n",
    size = mb?.let { it * MB },
    bitRate = bitRate,
    duration = seconds,
    playCount = plays,
    starred = if (starred) Instant.parse("2026-10-01T00:00:00Z") else null,
    created = Instant.parse("2026-09-%02dT00:00:00Z".format(createdDay))
)

private fun libId(n: Int) = SongId("0190a5c8-0000-7000-8000-%012d".format(n))

private fun candidates(vararg songs: Song) = songs.map(LibraryCandidate::of)

class LibrarySelectorTest {
    @Test
    fun `starred songs come first, then the most played, then the newest`() {
        val picked = LibrarySelector.select(
            candidates(
                song(1, plays = 50),
                song(2, plays = 1, starred = true),
                song(3, plays = 50, createdDay = 20),
                song(4, plays = null, createdDay = 5),
                song(5, plays = null, createdDay = 9)
            ),
            limitBytes = 100 * MB
        )
        assertEquals(
            listOf(libId(2), libId(3), libId(1), libId(5), libId(4)),
            picked.chosen.map { it.id }
        )
    }

    @Test
    fun `ties break on the id so a sync does not swap songs for nothing`() {
        val songs = listOf(song(3), song(1), song(2))
        val a = LibrarySelector.select(candidates(*songs.toTypedArray()), 2 * MB)
        val b = LibrarySelector.select(candidates(*songs.reversed().toTypedArray()), 2 * MB)
        assertEquals(listOf(libId(1), libId(2)), a.chosen.map { it.id })
        assertEquals(a.chosen, b.chosen)
    }

    @Test
    fun `the limit ends the selection and the rest is reported`() {
        val picked = LibrarySelector.select(
            candidates(
                song(1, mb = 4, starred = true),
                song(2, mb = 5, plays = 9),
                song(3, mb = 1, plays = 1)
            ),
            limitBytes = 8 * MB
        )
        // 4 MB fits, 5 MB would make 9: stop, even though the 1 MB song would still fit.
        assertEquals(listOf(libId(1)), picked.chosen.map { it.id })
        val report = picked.report
        assertEquals(3, report.totalCount)
        assertEquals(10 * MB, report.totalBytes)
        assertEquals(1, report.keptCount)
        assertEquals(4 * MB, report.keptBytes)
        assertEquals(2, report.leftOutCount)
        assertEquals(6 * MB, report.leftOutBytes)
        assertFalse(report.estimated)
    }

    @Test
    fun `a song that fits exactly is kept`() {
        val picked = LibrarySelector.select(candidates(song(1, mb = 2), song(2, mb = 2)), 4 * MB)
        assertEquals(2, picked.chosen.size)
        assertEquals(0, picked.report.leftOutCount)
    }

    @Test
    fun `no room keeps nothing`() {
        val picked = LibrarySelector.select(candidates(song(1)), limitBytes = 0)
        assertTrue(picked.chosen.isEmpty())
        assertEquals(1, picked.report.leftOutCount)
    }

    @Test
    fun `songs kept on their own cost no room and are not in the result`() {
        val picked = LibrarySelector.select(
            candidates(song(1, mb = 6, starred = true), song(2, mb = 5), song(3, mb = 5)),
            limitBytes = 10 * MB,
            alreadyKept = setOf(libId(1))
        )
        assertEquals(listOf(libId(2), libId(3)), picked.chosen.map { it.id })
        assertEquals(2, picked.report.totalCount)
        assertEquals(10 * MB, picked.report.totalBytes)
    }

    @Test
    fun `a song listed twice counts once`() {
        val picked = LibrarySelector.select(candidates(song(1), song(1)), 10 * MB)
        assertEquals(1, picked.report.totalCount)
    }

    @Test
    fun `an empty library selects nothing`() {
        val picked = LibrarySelector.select(emptyList(), 10 * MB)
        assertEquals(LibraryReport(0, 0, 0, 0, false), picked.report)
    }

    @Test
    fun `a missing size is estimated from bitrate and duration, else a typical song`() {
        val known = LibraryCandidate.of(song(1, mb = 3))
        assertEquals(3 * MB, known.bytes)
        assertFalse(known.estimated)

        val byBitRate = LibraryCandidate.of(song(2, mb = null, bitRate = 128, seconds = 100))
        assertEquals(128_000L / 8 * 100, byBitRate.bytes)
        assertTrue(byBitRate.estimated)

        val unknown = LibraryCandidate.of(song(3, mb = null))
        assertEquals(LibraryCandidate.FALLBACK_BYTES, unknown.bytes)
        assertTrue(unknown.estimated)

        // A zero size is not a size.
        assertTrue(LibraryCandidate.of(song(4, mb = 0)).estimated)

        val report = LibrarySelector.select(listOf(known, byBitRate), 100 * MB).report
        assertTrue(report.estimated)
    }

    @Test
    fun `plays, star and creation date come from the song`() {
        val bare = LibraryCandidate.of(Song(libId(1), "Bare"))
        assertEquals(0, bare.playCount)
        assertEquals(0, bare.createdMs)
        assertFalse(bare.starred)
        val full = LibraryCandidate.of(song(2, plays = 7, starred = true))
        assertEquals(7, full.playCount)
        assertTrue(full.starred)
    }
}

class LibraryOfflinePlannerTest {
    @Test
    fun `library songs are downloaded and freed with the library`() {
        val selection = OfflineSelection(
            tracks = listOf(PlayableTrack(libId(1), "One", "A")),
            library = LibraryOffline(
                songs = listOf(
                    PlayableTrack(libId(1), "One", "A"),
                    PlayableTrack(libId(2), "Two", "A")
                )
            )
        )
        val plan = OfflineSyncPlanner.plan(selection, downloaded = setOf(libId(3)))
        assertEquals(listOf(libId(1), libId(2)), plan.add.map { it.id })
        assertEquals(setOf(libId(3)), plan.remove)
        assertTrue(plan.complete)
    }

    @Test
    fun `nothing is freed while the library was never read`() {
        val selection = OfflineSelection(library = LibraryOffline())
        val plan = OfflineSyncPlanner.plan(selection, downloaded = setOf(libId(1)))
        assertFalse(plan.complete)
        assertTrue(plan.remove.isEmpty())
    }

    @Test
    fun `explicit ids include members and the library ids of yt songs`() {
        val yt = SongId("yt:" + "A".repeat(11))
        val selection = OfflineSelection(
            tracks = listOf(PlayableTrack(yt, "Y", "A"), PlayableTrack(libId(1), "One", "A")),
            collections = listOf(
                OfflineCollection(
                    CollectionKind.ALBUM,
                    "al",
                    "Album",
                    listOf(PlayableTrack(libId(2), "Two", "A"))
                ),
                OfflineCollection(CollectionKind.PLAYLIST, "pl", "Unread")
            ),
            aliases = mapOf(yt to libId(9)),
            library = LibraryOffline(songs = listOf(PlayableTrack(libId(5), "Five", "A")))
        )
        assertEquals(setOf(libId(9), libId(1), libId(2)), selection.explicitIds())
        assertFalse(selection.isEmpty)
        assertFalse(OfflineSelection(library = LibraryOffline()).isEmpty)
    }
}

private class LibraryStore(initial: OfflineSelection = OfflineSelection()) : OfflineSelectionStore {
    val state = MutableStateFlow(initial)
    override val selection = state

    override suspend fun update(transform: (OfflineSelection) -> OfflineSelection) {
        state.value = transform(state.value)
    }
}

private class LibraryQueue(val ids: MutableSet<SongId> = mutableSetOf()) : DownloadQueue {
    val added = mutableListOf<PlayableTrack>()

    override suspend fun knownIds(): Set<SongId> = ids.toSet()

    override suspend fun failedIds(): Set<SongId> = emptySet()

    override suspend fun add(track: PlayableTrack) {
        added += track
        ids += track.id
    }

    override suspend fun remove(id: SongId) {
        ids -= id
    }
}

class LibraryOfflineSyncTest {
    private val api = mockk<TunesApi> {
        every { coverArtUrl(any(), any()) } returns "https://music.example/cover".toHttpUrl()
    }

    private fun library(vararg songs: Song) {
        coEvery { api.librarySongs(any(), any()) } coAnswers {
            val offset = firstArg<Int>()
            val count = secondArg<Int>()
            TunesResult.Success(songs.drop(offset).take(count))
        }
    }

    private fun syncer(store: LibraryStore, queue: LibraryQueue, on: Boolean, limitMb: Int = 100) =
        OfflineSyncer(api, store, queue, playerSettings(on, limitMb))

    @Test
    fun `a sync downloads the library, frees songs that left it and keeps the report`() = runTest {
        val store = LibraryStore(
            OfflineSelection(
                library = LibraryOffline(songs = listOf(PlayableTrack(libId(9), "Gone", "A")))
            )
        )
        val queue = LibraryQueue(mutableSetOf(libId(9)))
        library(song(1), song(2, starred = true), song(3, plays = 4))

        val plan = syncer(store, queue, on = true).sync()

        assertEquals(setOf(libId(1), libId(2), libId(3)), queue.added.map { it.id }.toSet())
        assertEquals(setOf(libId(9)), plan.remove)
        assertFalse(libId(9) in queue.ids)
        val saved = requireNotNull(store.state.value.library)
        assertEquals(3, saved.songs?.size)
        assertEquals(3, saved.report?.keptCount)
        assertEquals(3 * MB, saved.report?.keptBytes)
    }

    @Test
    fun `a new library song downloads on the next sync`() = runTest {
        val store = LibraryStore()
        val queue = LibraryQueue()
        library(song(1))
        syncer(store, queue, on = true).sync()
        assertEquals(listOf(libId(1)), queue.added.map { it.id })

        library(song(1), song(2))
        syncer(store, queue, on = true).sync()
        assertEquals(listOf(libId(1), libId(2)), queue.added.map { it.id })
    }

    @Test
    fun `the library is read page by page`() = runTest {
        val songs = (1..501).map { song(it, mb = 1) }.toTypedArray()
        library(*songs)
        val store = LibraryStore()
        syncer(store, LibraryQueue(), on = true, limitMb = 10_000).sync()
        assertEquals(501, store.state.value.library?.songs?.size)
    }

    @Test
    fun `a library that does not fit keeps the priority songs and says what was left out`() =
        runTest {
            val store = LibraryStore()
            val queue = LibraryQueue()
            library(
                song(1, mb = 40, plays = 100),
                song(2, mb = 40, starred = true),
                song(3, mb = 40, plays = 5),
                song(4, mb = 40)
            )

            syncer(store, queue, on = true, limitMb = 100).sync()

            // 100 MB: the star (40) and the most played (40); the next 40 would make 120.
            assertEquals(setOf(libId(1), libId(2)), queue.ids)
            val report = store.state.value.library?.report
            assertEquals(4, report?.totalCount)
            assertEquals(2, report?.keptCount)
            assertEquals(2, report?.leftOutCount)
            assertEquals(80 * MB, report?.leftOutBytes)
        }

    @Test
    fun `explicit downloads are never evicted and do not use the limit`() = runTest {
        val explicit = PlayableTrack(libId(1), "Explicit", "A")
        val store = LibraryStore(
            OfflineSelection(
                collections = listOf(
                    OfflineCollection(CollectionKind.ALBUM, "al", "Album", listOf(explicit))
                )
            )
        )
        val queue = LibraryQueue(mutableSetOf(libId(1)))
        coEvery { api.album(AlbumId("al")) } returns
            TunesResult.Success(Album(AlbumId("al"), "Album", song = listOf(song(1, mb = 90))))
        library(song(1, mb = 90, starred = true), song(2, mb = 90, plays = 3), song(3, mb = 90))

        syncer(store, queue, on = true, limitMb = 100).sync()

        // 1 is the album's and costs nothing; 2 fits the 100 MB; 3 does not.
        assertEquals(setOf(libId(1), libId(2)), queue.ids)
        val saved = store.state.value
        assertEquals(listOf(libId(2)), saved.library?.songs?.map { it.id })
        assertEquals(2, saved.library?.report?.totalCount)
    }

    @Test
    fun `turning the setting off frees only what it had downloaded`() = runTest {
        val kept = PlayableTrack(libId(1), "Mine", "A")
        val store = LibraryStore(
            OfflineSelection(
                tracks = listOf(kept),
                library = LibraryOffline(
                    songs = listOf(kept, PlayableTrack(libId(2), "Library", "A"))
                )
            )
        )
        val queue = LibraryQueue(mutableSetOf(libId(1), libId(2)))

        val plan = syncer(store, queue, on = false).sync()

        assertEquals(setOf(libId(2)), plan.remove)
        assertEquals(setOf(libId(1)), queue.ids)
        assertNull(store.state.value.library)
        coVerify(exactly = 0) { api.librarySongs(any(), any()) }
    }

    @Test
    fun `an unreadable library keeps what it had and frees nothing`() = runTest {
        val store = LibraryStore(
            OfflineSelection(
                library = LibraryOffline(songs = listOf(PlayableTrack(libId(1), "One", "A")))
            )
        )
        val queue = LibraryQueue(mutableSetOf(libId(1)))
        coEvery { api.librarySongs(any(), any()) } returns TunesResult.NetworkError(IOException())

        syncer(store, queue, on = true).sync()

        assertEquals(setOf(libId(1)), queue.ids)
        assertEquals(listOf(libId(1)), store.state.value.library?.songs?.map { it.id })
    }

    @Test
    fun `a first sync that cannot read the library stays pending`() = runTest {
        val store = LibraryStore()
        val queue = LibraryQueue(mutableSetOf(libId(7)))
        coEvery { api.librarySongs(any(), any()) } returns TunesResult.NetworkError(IOException())

        syncer(store, queue, on = true).sync()

        val library = requireNotNull(store.state.value.library)
        assertNull(library.songs)
        // Not read yet: the unrelated download is not touched.
        assertEquals(setOf(libId(7)), queue.ids)
    }

    @Test
    fun `a page failing half way does not shrink the library`() = runTest {
        val first = (1..500).map { song(it) }
        coEvery { api.librarySongs(0, any()) } returns TunesResult.Success(first)
        coEvery { api.librarySongs(500, any()) } returns TunesResult.NetworkError(IOException())
        assertNull(syncer(LibraryStore(), LibraryQueue(), on = true).readLibrary())
    }

    @Test
    fun `external songs in a listing are ignored`() = runTest {
        val external = Song(SongId("yt:" + "B".repeat(11)), "Out there", size = MB)
        library(external, song(1))
        val scan = syncer(LibraryStore(), LibraryQueue(), on = true).readLibrary()
        assertEquals(listOf(libId(1)), scan?.songs?.map { it.id })
    }

    @Test
    fun `turning it off during the sync wins`() = runTest {
        val settings = playerSettings(libraryOffline = true)
        library(song(1))
        coEvery { api.librarySongs(any(), any()) } coAnswers {
            settings.settings.value = PlayerSettings(libraryOffline = false)
            TunesResult.Success(listOf(song(1)))
        }
        val store = LibraryStore()
        val queue = LibraryQueue()

        OfflineSyncer(api, store, queue, settings).sync()

        assertNull(store.state.value.library)
        assertTrue(queue.added.isEmpty())
    }

    @Test
    fun `the report of a scan counts only what the user does not keep`() = runTest {
        library(song(1, mb = 10), song(2, mb = 10))
        val scan = requireNotNull(syncer(LibraryStore(), LibraryQueue(), on = true).readLibrary())
        val report = scan.report(limitBytes = 5 * MB, alreadyKept = setOf(libId(1)))
        assertEquals(1, report.totalCount)
        assertEquals(1, report.leftOutCount)
    }
}
