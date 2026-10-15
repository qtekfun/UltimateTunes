// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.session

import android.net.Uri
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.Timeline
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.model.ReplayGain
import com.qtekfun.ultimatetunes.core.api.model.Song
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.api.model.TrackState
import com.qtekfun.ultimatetunes.core.api.model.TrackStatus
import com.qtekfun.ultimatetunes.core.player.cache.CacheJanitor
import com.qtekfun.ultimatetunes.core.player.cache.CacheView
import com.qtekfun.ultimatetunes.core.player.cache.StatusPoller
import com.qtekfun.ultimatetunes.core.player.gain.ReplayGainSource
import com.qtekfun.ultimatetunes.core.player.prefetch.PrefetchPlanner
import com.qtekfun.ultimatetunes.core.player.prefetch.PrefetchTarget
import com.qtekfun.ultimatetunes.core.player.prefetch.Prefetcher
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.every
import io.mockk.mockk
import io.mockk.mockkStatic
import io.mockk.slot
import io.mockk.unmockkStatic
import io.mockk.verify
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import okhttp3.HttpUrl.Companion.toHttpUrl
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test

private val LIB = SongId("0190a5c8-0000-7000-8000-000000000001")
private val LIB_NEW = SongId("0190a5c8-0000-7000-8000-000000000009")
private val YT = SongId("yt:AAAAAAAAAAA")

@OptIn(ExperimentalCoroutinesApi::class)
class PlaybackEngineTest {
    /** A queue the mocked player plays, at [index]. */
    private class Queue(var items: MutableList<MediaItem>, var index: Int = 0)

    private val queue = Queue(mutableListOf(item(LIB), item(YT), item(YT)))
    private val player = mockk<Player>(relaxed = true) {
        every { currentMediaItem } answers { queue.items.getOrNull(queue.index) }
        every { currentMediaItemIndex } answers { queue.index }
        every { mediaItemCount } answers { queue.items.size }
        every { getMediaItemAt(any()) } answers { queue.items[firstArg()] }
        every { nextMediaItemIndex } answers {
            if (queue.index + 1 < queue.items.size) queue.index + 1 else C.INDEX_UNSET
        }
        every { previousMediaItemIndex } answers {
            if (queue.index > 0) queue.index - 1 else C.INDEX_UNSET
        }
        every { replaceMediaItem(any(), any()) } answers {
            queue.items[firstArg()] = secondArg()
        }
    }
    private val volume = slot<Float>()
    private val api = mockk<TunesApi> {
        every { streamUrl(any()) } returns "https://music.example/rest/stream".toHttpUrl()
    }
    private val target = object : PrefetchTarget {
        val calls = mutableListOf<String>()

        override fun isAvailable(id: SongId) = false

        override suspend fun requestOnServer(id: SongId): Boolean {
            calls += "request $id"
            return true
        }

        override suspend fun preload(id: SongId, bytes: Long): Boolean {
            calls += "preload $id"
            return true
        }
    }
    private val cache = object : CacheView {
        val keys = mutableSetOf("yt:BBBBBBBBBBB", YT.value)
        val sweeps = mutableListOf<Set<String>>()

        override fun keys(): Set<String> = keys.toSet().also { sweeps += it }

        override fun contentLength(key: String): Long? = null

        override fun cachedBytes(key: String, limit: Long) = 1L

        override fun remove(key: String) {
            keys -= key
        }
    }
    private val statuses = ArrayDeque<TunesResult<TrackStatus>>()

    @BeforeEach
    fun mockUri() {
        every { player.volume = capture(volume) } answers { }
        mockkStatic(Uri::class)
        every { Uri.parse(any()) } returns mockk(relaxed = true)
    }

    @AfterEach
    fun unmockUri() {
        unmockkStatic(Uri::class)
    }

    private fun engine(scope: TestScope) = PlaybackEngine(
        player = player,
        api = api,
        prefetcher = Prefetcher(PrefetchPlanner(preloadBytes = 10), target, scope),
        poller = StatusPoller(fetch = { statuses.removeFirst() }, sleep = {}),
        janitor = CacheJanitor(cache),
        gains = ReplayGainSource(api),
        scope = scope,
        io = StandardTestDispatcher(scope.testScheduler)
    )

    @Test
    fun `starting prefetches the next song, sweeps the cache and applies ReplayGain`() = runTest {
        coEvery { api.song(LIB) } returns
            TunesResult.Success(Song(LIB, "T", replayGain = ReplayGain(trackGain = -6.0)))
        val engine = engine(this)

        engine.start()
        // Before getSong answers, the song already plays at the level of unknown songs.
        assertEquals(UNKNOWN, volume.captured, 0.001f)
        advanceUntilIdle()

        verify { player.addListener(engine) }
        assertEquals(listOf("request $YT", "preload $YT"), target.calls)
        // The next song (YT) is in use; the other incomplete yt entry is dropped.
        assertEquals(setOf(YT.value), cache.keys)
        assertEquals(0.501f, volume.captured, 0.001f)
    }

    @Test
    fun `a yt song is polled until archived, then queued again as the library song`() = runTest {
        statuses += TunesResult.Success(
            TrackStatus(YT, null, TrackState.DOWNLOADING, 0.5, 1, 3, streamable = true)
        )
        statuses += TunesResult.Success(
            TrackStatus(YT, LIB_NEW, TrackState.READY, 1.0, 1, 3, streamable = true)
        )
        queue.index = 1
        val engine = engine(this)

        engine.start()
        advanceUntilIdle()

        // The song playing keeps its id; its later copy in the queue becomes the library song.
        assertEquals(YT.value, queue.items[1].mediaId)
        assertEquals(LIB_NEW.value, queue.items[2].mediaId)
        assertEquals(LIB_NEW.value, queue.items[2].localConfiguration?.customCacheKey)
        // No gain lookup for an external song: it plays at the gain for unknown songs.
        assertEquals(UNKNOWN, volume.captured, 0.001f)
    }

    @Test
    fun `offline only prefetches nothing and asks nothing`() = runTest {
        queue.index = 1
        val engine = engine(this)
        engine.offlineOnly = true

        engine.start()
        advanceUntilIdle()

        assertTrue(target.calls.isEmpty())
        assertEquals(UNKNOWN, volume.captured, 0.001f)
    }

    @Test
    fun `a known gain is applied at once, also offline, and sets the level of unknown songs`() =
        runTest {
            // Its peak lowers it to 0.4, below the -6 dB (0.501) that unknown songs then get.
            val gain = ReplayGain(trackGain = -6.0, trackPeak = 2.5)
            coEvery { api.song(LIB) } returns TunesResult.Success(Song(LIB, "T", replayGain = gain))
            val engine = engine(this)
            engine.start()
            advanceUntilIdle()
            engine.offlineOnly = true

            // The external song plays as loud as the library songs seen so far.
            queue.index = 1
            engine.onMediaItemTransition(queue.items[1], Player.MEDIA_ITEM_TRANSITION_REASON_AUTO)
            assertEquals(0.501f, volume.captured, 0.001f)

            // Back to the library song, offline: its remembered gain, without asking again.
            queue.index = 0
            engine.onMediaItemTransition(queue.items[0], Player.MEDIA_ITEM_TRANSITION_REASON_SEEK)
            assertEquals(0.4f, volume.captured, 0.001f)
            coVerify(exactly = 1) { api.song(LIB) }
        }

    @Test
    fun `queue moves and timeline changes are followed, the same song is not redone`() = runTest {
        coEvery { api.song(any()) } returns TunesResult.Success(Song(LIB, "T"))
        val engine = engine(this)
        engine.start()
        advanceUntilIdle()

        engine.onTimelineChanged(Timeline.EMPTY, Player.TIMELINE_CHANGE_REASON_PLAYLIST_CHANGED)
        queue.index = 2
        statuses += TunesResult.Success(
            TrackStatus(YT, null, TrackState.FAILED, 0.0, 3, 3, streamable = false)
        )
        engine.onMediaItemTransition(queue.items[2], Player.MEDIA_ITEM_TRANSITION_REASON_AUTO)
        advanceUntilIdle()

        // Last song: nothing upcoming, and the failed poll left the queue alone.
        assertEquals(YT.value, queue.items[2].mediaId)
        assertEquals(UNKNOWN, volume.captured, 0.001f)
        engine.release()
        verify { player.removeListener(engine) }
    }

    @Test
    fun `load errors skip ahead a few times in a row, then stop`() = runTest {
        coEvery { api.song(any()) } returns TunesResult.Success(Song(LIB, "T"))
        every { player.hasNextMediaItem() } returns true
        val engine = engine(this)
        engine.start()
        val error = mockk<PlaybackException>()

        repeat(4) { engine.onPlayerError(error) }

        verify(exactly = 3) { player.seekToNextMediaItem() }
        assertEquals(List(4) { LIB }, engine.failed)

        engine.onIsPlayingChanged(false)
        engine.onPlayerError(error)
        verify(exactly = 3) { player.seekToNextMediaItem() }

        engine.onIsPlayingChanged(true)
        engine.onPlayerError(error)
        verify(exactly = 4) { player.seekToNextMediaItem() }
    }

    @Test
    fun `an error at the end of the queue does not skip, and failures are bounded`() = runTest {
        coEvery { api.song(any()) } returns TunesResult.Success(Song(LIB, "T"))
        every { player.hasNextMediaItem() } returns false
        val engine = engine(this)
        engine.start()

        repeat(60) { engine.onPlayerError(mockk<PlaybackException>()) }

        verify(exactly = 0) { player.seekToNextMediaItem() }
        assertEquals(50, engine.failed.size)
    }

    @Test
    fun `an empty queue does nothing`() = runTest {
        queue.items.clear()
        val engine = engine(this)
        engine.start()
        engine.onPlayerError(mockk<PlaybackException>())
        advanceUntilIdle()

        assertTrue(target.calls.isEmpty())
        assertTrue(engine.failed.isEmpty())
        assertTrue(!volume.isCaptured)
    }

    private companion object {
        /** -9 dB, the volume of a song without ReplayGain when no library gain is known. */
        const val UNKNOWN = 0.355f

        fun item(id: SongId): MediaItem = MediaItem.Builder().setMediaId(id.value).build()
    }
}
