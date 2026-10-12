// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.e2e

import android.content.Context
import androidx.annotation.OptIn
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.database.StandaloneDatabaseProvider
import androidx.media3.datasource.cache.NoOpCacheEvictor
import androidx.media3.datasource.cache.SimpleCache
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.test.platform.app.InstrumentationRegistry
import com.qtekfun.ultimatetunes.core.api.InMemoryServerConfigSource
import com.qtekfun.ultimatetunes.core.api.ServerConfig
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesApiFactory
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.model.ApiKeySecret
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.api.model.TrackState
import com.qtekfun.ultimatetunes.core.api.model.TrackStatus
import com.qtekfun.ultimatetunes.core.player.cache.AdjustableLruEvictor
import com.qtekfun.ultimatetunes.core.player.cache.CachePolicy
import com.qtekfun.ultimatetunes.core.player.media.MediaCacheView
import com.qtekfun.ultimatetunes.core.player.media.MediaCaches
import com.qtekfun.ultimatetunes.core.player.media.MediaDataSources
import com.qtekfun.ultimatetunes.core.player.media.MediaItems
import java.io.File
import java.io.IOException
import java.time.Clock
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.Response
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Before
import org.junit.Test

/**
 * The device half of the end-to-end suite (PLAN T20): the phone against the real test stack
 * (fake YouTube), through the app's own `:core:api` client and `:core:player` Media3 stack.
 * Search → first play of an external song while the server downloads it → archived → replay
 * from the server's library file through the play cache → replay again with the network cut.
 *
 * It runs only when `tools/e2e/run.sh` passes the stack's URL and a key as instrumentation
 * arguments (`utE2eUrl`, `utE2eKey`); any other run of the test APK skips it. It never touches
 * the app's saved server, caches or downloads: everything lives in its own directory and memory.
 * Audio is decoded by the platform only with `utE2eDecode=true`; by default the extracted samples
 * go to a [DiscardingAudioRenderer] (see there why).
 */
@OptIn(UnstableApi::class)
class ServerEndToEndTest {
    private val context: Context = InstrumentationRegistry.getInstrumentation().targetContext
    private val arguments = InstrumentationRegistry.getArguments()
    private val root = File(context.cacheDir, "server-e2e-test")
    private val network = NetworkSwitch()
    private val decode = arguments.getString(ARG_DECODE).toBoolean()
    private var caches: MediaCaches? = null
    private var database: StandaloneDatabaseProvider? = null
    private lateinit var api: TunesApi
    private lateinit var sources: MediaDataSources

    @Before
    fun setUp() {
        val url = arguments.getString(ARG_URL)
        val key = arguments.getString(ARG_KEY)
        assumeTrue("end-to-end: run through tools/e2e/run.sh", url != null && key != null)
        root.deleteRecursively()
        val database = StandaloneDatabaseProvider(context).also { this.database = it }
        val evictor = AdjustableLruEvictor(LARGE)
        val media = MediaCaches(
            play = SimpleCache(File(root, "play"), evictor, database),
            evictor = evictor,
            downloads = SimpleCache(File(root, "offline"), NoOpCacheEvictor(), database)
        )
        caches = media
        val config = InMemoryServerConfigSource(
            ServerConfig(requireNotNull(url).toHttpUrl(), ApiKeySecret(requireNotNull(key)))
        )
        val client = TunesApiFactory.httpClient(
            config,
            OkHttpClient.Builder().addInterceptor(network).build()
        )
        api = TunesApiFactory.create(client, config, Clock.systemUTC())
        sources = MediaDataSources(client, media)
    }

    @After
    fun tearDown() {
        caches?.let {
            (it.play as SimpleCache).release()
            (it.downloads as SimpleCache).release()
            // Drops the caches' index tables too, so the app's Media3 database keeps no orphans.
            val provider = requireNotNull(database)
            SimpleCache.delete(File(root, "play"), provider)
            SimpleCache.delete(File(root, "offline"), provider)
            root.deleteRecursively()
        }
    }

    @Test
    fun anExternalSongPlaysWhileDownloadingThenFromTheLibraryThenOffline() = runBlocking {
        val external = success(api.search(TITLE)).tracks.single { it.title == TITLE }
        assertEquals("a fresh stack has the song on YouTube only", SONG, external.id)
        assertTrue(external.isExternal)

        // First play: the server streams the song while its worker downloads it.
        assertNull(playToEnd(external.id))
        val archived = waitUntilReady(external.id)
        val libraryId = requireNotNull(archived.trackId)
        val song = success(api.song(libraryId))
        assertEquals("opus", song.suffix)

        // Replay: the library file, now through the play cache, completely.
        val beforeReplay = network.requests.get()
        assertNull(playToEnd(libraryId))
        assertTrue("the replay came from the server", network.requests.get() > beforeReplay)
        val view = MediaCacheView(requireNotNull(caches).play)
        val key = CachePolicy.cacheKey(libraryId)
        assertEquals(song.size, view.contentLength(key))
        val complete = CachePolicy.isComplete(
            view.contentLength(key),
            view.cachedBytes(key, Long.MAX_VALUE)
        )
        assertTrue("the whole song is cached", complete)

        // Network cut: the server is unreachable, the cached song still plays.
        network.online.set(false)
        val beforePing = network.requests.get()
        assertTrue(api.ping() is TunesResult.NetworkError)
        assertTrue("a blocked request is counted", network.requests.get() > beforePing)
        val atCut = network.requests.get()
        assertNull(playToEnd(libraryId))
        assertEquals("the offline replay never asked the server", atCut, network.requests.get())
    }

    private suspend fun waitUntilReady(id: SongId): TrackStatus = withTimeout(READY_TIMEOUT_MS) {
        var status = success(api.trackStatus(id))
        while (status.state != TrackState.READY) {
            assertTrue("the download failed: $status", status.state.isInProgress)
            delay(POLL_MS)
            status = success(api.trackStatus(id))
        }
        status
    }

    /** Plays [id] as the app does (stream URL, played id as cache key); returns the error, if any. */
    private fun playToEnd(id: SongId): PlaybackException? {
        val item = MediaItems.resolve(MediaItem.Builder().setMediaId(id.value).build(), api)
        val done = CountDownLatch(1)
        var failure: PlaybackException? = null
        lateinit var player: ExoPlayer
        val renderer = DiscardingAudioRenderer()
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        instrumentation.runOnMainSync {
            val builder = if (decode) {
                ExoPlayer.Builder(context)
            } else {
                ExoPlayer.Builder(context, DiscardingAudioRenderer.factory(renderer))
            }
            player = builder
                .setMediaSourceFactory(DefaultMediaSourceFactory(sources.playback))
                .build()
            player.volume = 0f
            player.addListener(object : Player.Listener {
                override fun onPlaybackStateChanged(playbackState: Int) {
                    if (playbackState == Player.STATE_ENDED) done.countDown()
                }

                override fun onPlayerError(error: PlaybackException) {
                    failure = error
                    done.countDown()
                }
            })
            player.setMediaItem(item)
            player.prepare()
            player.play()
        }
        val finished = done.await(PLAY_TIMEOUT_S, TimeUnit.SECONDS)
        instrumentation.runOnMainSync { player.release() }
        assertTrue("playback of $id finished in time", finished)
        val heard = decode || failure != null || renderer.samples.get() > 0
        assertTrue("audio reached the player", heard)
        return failure
    }

    private fun <T> success(result: TunesResult<T>): T {
        assertTrue("expected a success, got $result", result is TunesResult.Success)
        return (result as TunesResult.Success).value
    }

    /**
     * Counts every request the phone attempts, online or not, and cuts the network on demand
     * before anything leaves the phone.
     */
    private class NetworkSwitch : Interceptor {
        val online = AtomicBoolean(true)
        val requests = AtomicInteger()

        override fun intercept(chain: Interceptor.Chain): Response {
            requests.incrementAndGet()
            if (!online.get()) throw IOException("network cut")
            return chain.proceed(chain.request())
        }
    }

    private companion object {
        const val ARG_URL = "utE2eUrl"
        const val ARG_KEY = "utE2eKey"
        const val ARG_DECODE = "utE2eDecode"

        /** A song of the server's fake catalog (server/src/ultimatetunes/search/fake.py). */
        const val TITLE = "Static Bloom"
        val SONG = SongId("yt:Hm3Vx8Nq2Lp")

        const val LARGE = 64L * 1024 * 1024
        const val PLAY_TIMEOUT_S = 90L
        const val READY_TIMEOUT_MS = 120_000L
        const val POLL_MS = 1_000L
    }
}
