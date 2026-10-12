// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.session

import android.net.Uri
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.datasource.cache.Cache
import androidx.media3.exoplayer.ExoPlayer
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.player.PlayerSettingsSource
import com.qtekfun.ultimatetunes.core.player.cache.AdjustableLruEvictor
import com.qtekfun.ultimatetunes.core.player.cache.CachePolicy
import com.qtekfun.ultimatetunes.core.player.media.MediaCaches
import com.qtekfun.ultimatetunes.core.player.media.MediaDataSources
import io.mockk.every
import io.mockk.mockk
import io.mockk.mockkStatic
import io.mockk.unmockkAll
import io.mockk.verify
import kotlinx.coroutines.test.runTest
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test

class PlayerAssemblyTest {
    private val evictor = AdjustableLruEvictor(1)
    private val caches = MediaCaches(mockk<Cache>(relaxed = true), evictor, mockk())
    private val api = mockk<TunesApi>()
    private val settings = mockk<PlayerSettingsSource>()
    private val assembly = PlayerAssembly(
        context = mockk(),
        api = api,
        caches = caches,
        sources = MediaDataSources(OkHttpClient(), caches),
        settings = settings
    )

    @AfterEach
    fun unmock() = unmockkAll()

    @Test
    fun `the engine follows the player it is built for`() = runTest {
        val player = mockk<ExoPlayer>(relaxed = true) {
            every { currentMediaItem } returns null
            every { nextMediaItemIndex } returns C.INDEX_UNSET
        }
        val engine = assembly.newEngine(player, this)
        engine.start()
        verify { player.addListener(engine) }
        engine.release()
    }

    @Test
    fun `the cache size follows the settings`() {
        assembly.resizeCache(1024)
        assertEquals(CachePolicy.maxBytes(1024), evictor.maxBytes)
    }

    @Test
    fun `items added by a controller get their stream URL`() {
        mockkStatic(Uri::class)
        every { Uri.parse(any()) } returns mockk(relaxed = true)
        every { api.streamUrl(any()) } returns "https://music.example/rest/stream".toHttpUrl()
        val callback = assembly.sessionCallback()

        val items = callback.onAddMediaItems(
            mockk(),
            mockk(),
            listOf(MediaItem.Builder().setMediaId("0190a5c8-0000-7000-8000-000000000001").build())
        ).get()

        assertEquals(
            "0190a5c8-0000-7000-8000-000000000001",
            items.single().localConfiguration?.customCacheKey
        )
    }
}
