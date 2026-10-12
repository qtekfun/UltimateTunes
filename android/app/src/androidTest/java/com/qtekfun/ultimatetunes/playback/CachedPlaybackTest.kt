// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.playback

import android.content.Context
import androidx.annotation.OptIn
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.database.StandaloneDatabaseProvider
import androidx.media3.datasource.DataSpec
import androidx.media3.datasource.cache.CacheDataSource
import androidx.media3.datasource.cache.CacheWriter
import androidx.media3.datasource.cache.NoOpCacheEvictor
import androidx.media3.datasource.cache.SimpleCache
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.test.platform.app.InstrumentationRegistry
import com.qtekfun.ultimatetunes.core.player.cache.AdjustableLruEvictor
import com.qtekfun.ultimatetunes.core.player.cache.CachePolicy
import com.qtekfun.ultimatetunes.core.player.media.MediaCacheView
import com.qtekfun.ultimatetunes.core.player.media.MediaCaches
import com.qtekfun.ultimatetunes.core.player.media.MediaDataSources
import java.io.File
import java.io.IOException
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * The real Media3 stack of the player (PLAN T17) on a device: a song plays through the play cache,
 * then plays again from the cache with the network off; an offline download plays without any
 * network. The "server" is an OkHttp interceptor serving generated silent audio with Range
 * support, so nothing leaves the phone and nothing is heard.
 */
@OptIn(UnstableApi::class)
class CachedPlaybackTest {
    private val context: Context = InstrumentationRegistry.getInstrumentation().targetContext
    private val root = File(context.cacheDir, "cached-playback-test")
    private val network = FakeAudioServer(silentWav(seconds = 2))
    private lateinit var caches: MediaCaches
    private lateinit var sources: MediaDataSources

    @Before
    fun setUp() {
        root.deleteRecursively()
        val database = StandaloneDatabaseProvider(context)
        val evictor = AdjustableLruEvictor(LARGE)
        caches = MediaCaches(
            play = SimpleCache(File(root, "play"), evictor, database),
            evictor = evictor,
            downloads = SimpleCache(File(root, "offline"), NoOpCacheEvictor(), database)
        )
        sources = MediaDataSources(OkHttpClient.Builder().addInterceptor(network).build(), caches)
    }

    @After
    fun tearDown() {
        (caches.play as SimpleCache).release()
        (caches.downloads as SimpleCache).release()
        root.deleteRecursively()
    }

    @Test
    fun aSongPlaysAgainFromTheCacheWithTheNetworkOff() {
        val item = item(KEY)
        assertNull(playToEnd(item))
        assertTrue("the first play reached the server", network.requests.get() > 0)
        val view = MediaCacheView(caches.play)
        assertEquals(network.body.size.toLong(), view.contentLength(KEY))
        assertTrue(
            CachePolicy.isComplete(view.contentLength(KEY), view.cachedBytes(KEY, Long.MAX_VALUE))
        )
        network.online.set(false)
        val before = network.requests.get()
        assertNull(playToEnd(item))
        assertEquals("the replay never asked the server", before, network.requests.get())
    }

    @Test
    fun anOfflineDownloadPlaysWithoutTheNetworkAndOutsideThePlayCache() {
        val downloadKey = "0190a5c8-0000-7000-8000-0000000000d1"
        CacheWriter(
            CacheDataSource.Factory()
                .setCache(caches.downloads)
                .setUpstreamDataSourceFactory(sources.http)
                .createDataSource(),
            DataSpec.Builder().setUri(URL).setKey(downloadKey).build(),
            null,
            null
        ).cache()

        network.online.set(false)
        assertNull(playToEnd(item(downloadKey)))
        assertTrue(downloadKey !in caches.play.keys)
    }

    @Test
    fun withTheNetworkOffAnUncachedSongFailsCleanly() {
        network.online.set(false)
        val error = playToEnd(item("0190a5c8-0000-7000-8000-0000000000e1"))
        assertNotNull(error)
        assertEquals(PlaybackIssue.NETWORK, PlaybackConnection.issueOf(error!!))
    }

    private fun item(key: String) = MediaItem.Builder().setUri(URL).setCustomCacheKey(key).build()

    /** Plays [item] to its end on the main thread; returns the error, if any. */
    private fun playToEnd(item: MediaItem): PlaybackException? {
        val done = CountDownLatch(1)
        var failure: PlaybackException? = null
        lateinit var player: ExoPlayer
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        instrumentation.runOnMainSync {
            player = ExoPlayer.Builder(context)
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
        val finished = done.await(TIMEOUT_S, TimeUnit.SECONDS)
        instrumentation.runOnMainSync { player.release() }
        assertTrue("playback finished in time", finished)
        return failure
    }

    /** Serves [body] at any URL, with Range support, while [online]. */
    private class FakeAudioServer(val body: ByteArray) : Interceptor {
        val online = AtomicBoolean(true)
        val requests = AtomicInteger()

        override fun intercept(chain: Interceptor.Chain): Response {
            if (!online.get()) throw IOException("network off")
            requests.incrementAndGet()
            val range = chain.request().header("Range")
                ?.removePrefix("bytes=")
                ?.split("-")
            val start = range?.getOrNull(0)?.toLongOrNull() ?: 0
            val end = range?.getOrNull(1)?.toLongOrNull() ?: (body.size - 1L)
            val slice = body.copyOfRange(start.toInt(), end.toInt() + 1)
            return Response.Builder()
                .request(chain.request())
                .protocol(Protocol.HTTP_1_1)
                .code(if (range == null) 200 else 206)
                .message("OK")
                .header("Accept-Ranges", "bytes")
                // Media3 caches a play only with a known size (T03a): send it, like the server.
                .header("Content-Length", slice.size.toString())
                .apply {
                    if (range != null) header("Content-Range", "bytes $start-$end/${body.size}")
                }
                .body(slice.toResponseBody("audio/wav".toMediaType()))
                .build()
        }
    }

    private companion object {
        const val URL = "https://music.example/rest/stream?id=x"
        const val KEY = "0190a5c8-0000-7000-8000-0000000000c1"
        const val LARGE = 64L * 1024 * 1024
        const val TIMEOUT_S = 30L
        const val SAMPLE_RATE = 8_000

        /** A mono 16-bit PCM WAV of [seconds] of silence. */
        fun silentWav(seconds: Int): ByteArray {
            val dataBytes = SAMPLE_RATE * 2 * seconds
            return ByteBuffer.allocate(44 + dataBytes).order(ByteOrder.LITTLE_ENDIAN).apply {
                put("RIFF".toByteArray())
                putInt(36 + dataBytes)
                put("WAVEfmt ".toByteArray())
                putInt(16)
                putShort(1)
                putShort(1)
                putInt(SAMPLE_RATE)
                putInt(SAMPLE_RATE * 2)
                putShort(2)
                putShort(16)
                put("data".toByteArray())
                putInt(dataBytes)
            }.array()
        }
    }
}
