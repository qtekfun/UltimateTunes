// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.media

import android.net.Uri
import android.os.Bundle
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.datasource.cache.Cache
import androidx.media3.datasource.cache.CacheDataSource
import androidx.media3.datasource.cache.ContentMetadata
import androidx.media3.datasource.okhttp.OkHttpDataSource
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.RequestReason
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.api.model.TrackState
import com.qtekfun.ultimatetunes.core.api.model.TrackStatus
import com.qtekfun.ultimatetunes.core.player.PlayableTrack
import com.qtekfun.ultimatetunes.core.player.cache.AdjustableLruEvictor
import com.qtekfun.ultimatetunes.core.player.cache.CachePolicy
import io.mockk.coEvery
import io.mockk.every
import io.mockk.mockk
import io.mockk.mockkConstructor
import io.mockk.mockkStatic
import io.mockk.unmockkAll
import io.mockk.verify
import java.io.IOException
import kotlinx.coroutines.test.runTest
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertSame
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

private val ID = SongId("0190a5c8-0000-7000-8000-000000000001")

/** A cache whose [key] has [length] bytes in total ([C.LENGTH_UNSET] when unknown). */
private fun cacheWith(key: String, length: Long, cached: (Long) -> Boolean): Cache = mockk {
    val metadata = mockk<ContentMetadata> {
        every { get(ContentMetadata.KEY_CONTENT_LENGTH, any<Long>()) } returns length
    }
    every { getContentMetadata(key) } returns metadata
    every { isCached(key, 0, any()) } answers { cached(thirdArg()) }
}

class MediaCachesTest {
    @Test
    fun `the start of a song counts when cached or downloaded, short songs entirely`() {
        val key = ID.value
        val play = cacheWith(key, length = 100) { it == 100L }
        val downloads = cacheWith(key, length = C.LENGTH_UNSET.toLong()) { false }
        val caches = MediaCaches(play, AdjustableLruEvictor(1), downloads)
        assertTrue(caches.hasStart(key, 1_000))

        val onlyDownloaded = MediaCaches(
            cacheWith(key, C.LENGTH_UNSET.toLong()) { false },
            AdjustableLruEvictor(1),
            cacheWith(key, 5_000) { it == 1_000L }
        )
        assertTrue(onlyDownloaded.hasStart(key, 1_000))

        val empty = MediaCaches(
            cacheWith(key, 0) { true },
            AdjustableLruEvictor(1),
            cacheWith(key, C.LENGTH_UNSET.toLong()) { false }
        )
        assertFalse(empty.hasStart(key, 1_000))
    }

    @Test
    fun `resizing goes through the evictor`() {
        val play = mockk<Cache>(relaxed = true)
        val evictor = AdjustableLruEvictor(1)
        MediaCaches(play, evictor, mockk()).resizePlayCache(512)
        assertEquals(CachePolicy.maxBytes(512), evictor.maxBytes)
    }

    @Test
    fun `the janitor's view reads lengths and bytes and removes resources`() {
        val key = "yt:AAAAAAAAAAA"
        val cache = cacheWith(key, 100) { true }
        every { cache.keys } returns setOf(key)
        every { cache.getCachedBytes(key, 0, any()) } answers { 40 }
        every { cache.removeResource(key) } returns Unit
        val unknown = cacheWith("other", C.LENGTH_UNSET.toLong()) { true }

        val view = MediaCacheView(cache)
        assertEquals(setOf(key), view.keys())
        assertEquals(100L, view.contentLength(key))
        assertNull(MediaCacheView(unknown).contentLength("other"))
        assertEquals(40, view.cachedBytes(key, 100))
        view.cachedBytes(key, Long.MAX_VALUE)
        verify { cache.getCachedBytes(key, 0, C.LENGTH_UNSET.toLong()) }
        view.remove(key)
        verify { cache.removeResource(key) }
    }

    @Test
    fun `playback reads downloads first, then the play cache`() {
        val play = mockk<Cache>()
        val downloads = mockk<Cache>()
        val sources =
            MediaDataSources(OkHttpClient(), MediaCaches(play, AdjustableLruEvictor(1), downloads))
        assertSame(play, sources.playCache.cache)
        assertTrue(sources.playback.createDataSource() is CacheDataSource)
        assertTrue(sources.http.createDataSource() is OkHttpDataSource)
    }
}

class MediaPrefetchTargetTest {
    private val api = mockk<TunesApi>()
    private val caches = MediaCaches(
        cacheWith(ID.value, 10) { true },
        AdjustableLruEvictor(1),
        cacheWith(ID.value, C.LENGTH_UNSET.toLong()) { false }
    )
    private val target =
        MediaPrefetchTarget(api, caches, MediaDataSources(OkHttpClient(), caches))

    @Test
    fun `availability comes from the caches`() {
        assertTrue(target.isAvailable(ID))
    }

    @Test
    fun `a request succeeds only with an answer`() = runTest {
        val yt = SongId("yt:AAAAAAAAAAA")
        coEvery { api.requestTrack(yt, RequestReason.PREFETCH) } returns
            TunesResult.Success(
                TrackStatus(yt, null, TrackState.QUEUED, 0.0, 0, 3, streamable = false)
            )
        coEvery { api.requestTrack(ID, RequestReason.PREFETCH) } returns
            TunesResult.NetworkError(IOException("off"))
        assertTrue(target.requestOnServer(yt))
        assertFalse(target.requestOnServer(ID))
    }

    @Test
    fun `no preload without a server`() = runTest {
        every { api.streamUrl(ID) } returns null
        assertFalse(target.preload(ID, 10))
    }
}

class MediaItemsTest {
    private val api = mockk<TunesApi>()

    @AfterEach
    fun unmock() = unmockkAll()

    private fun mockAndroid() {
        mockkStatic(Uri::class)
        every { Uri.parse(any()) } answers {
            mockk { every { this@mockk.toString() } returns firstArg() }
        }
        every { Uri.encode(any()) } answers { firstArg() }
        mockkConstructor(Bundle::class)
        every { anyConstructed<Bundle>().putString(any(), any()) } returns Unit
        every { anyConstructed<Bundle>().getString(any()) } returns null
    }

    @Test
    fun `resolving sets the stream URL and the played id as cache key`() {
        mockAndroid()
        every { api.streamUrl(ID) } returns "https://music.example/rest/stream?id=x".toHttpUrl()
        val item = MediaItem.Builder().setMediaId(ID.value).build()

        val resolved = MediaItems.resolve(item, api)

        assertEquals(
            "https://music.example/rest/stream?id=x",
            resolved.localConfiguration?.uri.toString()
        )
        assertEquals(ID.value, resolved.localConfiguration?.customCacheKey)
        assertEquals(ID, MediaItems.songOf(resolved))
    }

    @Test
    fun `without a server the URI never reaches the network`() {
        mockAndroid()
        every { api.streamUrl(any()) } returns null
        val other = SongId("0190a5c8-0000-7000-8000-000000000002")

        val resolved = MediaItems.withId(
            MediaItem.Builder().setMediaId(ID.value).build(),
            other,
            api
        )

        assertEquals("ut-offline:${other.value}", resolved.localConfiguration?.uri.toString())
        assertEquals(other.value, resolved.mediaId)
    }

    @Test
    fun `a track becomes an item and back`() {
        mockAndroid()
        val track = PlayableTrack(
            id = ID,
            title = "Harbour Lights",
            artist = "Northbound Static",
            album = "Low Tide",
            albumId = null,
            durationMs = 200_000,
            artworkUrl = "https://music.example/rest/getCoverArt?id=al-1",
            trackNumber = 4
        )
        val item = MediaItems.of(track)
        assertEquals(ID.value, item.mediaId)
        assertNull(item.localConfiguration)
        assertEquals(track, MediaItems.trackOf(item))
        assertNull(MediaItems.albumOf(item))
    }

    @Test
    fun `the album id travels in the extras`() {
        val extras = mockk<Bundle> { every { getString(any()) } returns "al-1" }
        val item = MediaItem.Builder()
            .setMediaId(ID.value)
            .setMediaMetadata(MediaMetadata.Builder().setExtras(extras).build())
            .build()
        assertEquals(AlbumId("al-1"), MediaItems.albumOf(item))
        val bare = MediaItems.trackOf(MediaItem.Builder().setMediaId(ID.value).build())
        assertEquals(PlayableTrack(ID, "", ""), bare)
    }
}
