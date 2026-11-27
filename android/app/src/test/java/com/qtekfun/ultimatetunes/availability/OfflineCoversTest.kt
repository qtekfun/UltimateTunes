// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.availability

import com.qtekfun.ultimatetunes.core.api.fake.FakeTunesServer
import com.qtekfun.ultimatetunes.core.api.model.CoverArtId
import com.qtekfun.ultimatetunes.core.player.offline.OfflineItem
import com.qtekfun.ultimatetunes.core.player.offline.OfflineState
import com.qtekfun.ultimatetunes.playback.toPlayable
import com.qtekfun.ultimatetunes.ui.FakeConnectivity
import com.qtekfun.ultimatetunes.ui.FakeOfflineControls
import com.qtekfun.ultimatetunes.ui.connectedApi
import com.qtekfun.ultimatetunes.ui.tile
import java.io.File
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import mockwebserver3.MockResponse
import okhttp3.Headers.Companion.headersOf
import okhttp3.OkHttpClient
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.io.TempDir

private const val ANY = "https://old.example.net/rest/getCoverArt.view?id="

class OfflineCoversTest {
    @TempDir
    lateinit var folder: File

    @Test
    fun `a cover is known by its id, whatever the address`() = runBlocking {
        val covers = OfflineCovers(folder)
        covers.keep(setOf("al-1", "al-2")) { if (it == "al-1") byteArrayOf(1, 2) else null }

        assertNotNull(covers.file("${ANY}al-1&size=600"))
        assertNotNull(covers.file("http://lan/music/rest/getCoverArt?id=al-1"))
        assertNull(covers.file("${ANY}al-2"))
        assertNull(covers.file("https://x.example.net/rest/stream?id=al-1"))
        assertNull(covers.file("not a url"))
        // Found again after a restart, and gone once no download wants it.
        assertNotNull(OfflineCovers(folder).file("${ANY}al-1"))
        covers.keep(emptySet()) { null }
        assertNull(covers.file("${ANY}al-1"))
        assertEquals(0, folder.list()?.size)
    }

    @Test
    fun `a cover already kept is not fetched again`() = runBlocking {
        val covers = OfflineCovers(folder)
        var fetched = 0
        repeat(2) {
            covers.keep(setOf("al-1")) {
                fetched++
                byteArrayOf(1)
            }
        }

        assertEquals(1, fetched)
    }

    @Test
    fun `the covers of finished downloads are fetched from the server`() = runBlocking {
        FakeTunesServer().start().use { server ->
            server.dispatcher.override("rest/getCoverArt") {
                MockResponse(
                    code = 200,
                    headers = headersOf("Content-Type", "image/png"),
                    body = "png"
                )
            }
            val api = connectedApi(server)
            val offline = FakeOfflineControls()
            val url = api.coverArtUrl(CoverArtId("al-7"), 600).toString()
            offline.mutableItems.value = listOf(
                OfflineItem(
                    tile(7).toPlayable().copy(artworkUrl = url),
                    OfflineState.DONE,
                    100f
                )
            )
            val covers = OfflineCovers(folder)
            val scope = CoroutineScope(SupervisorJob() + Dispatchers.Unconfined)
            val config = com.qtekfun.ultimatetunes.core.api.InMemoryServerConfigSource(
                server.serverConfig()
            )

            OfflineCoverSync(
                covers,
                offline,
                api,
                OkHttpClient(),
                config,
                FakeConnectivity(),
                scope,
                Dispatchers.Unconfined
            ).start()

            assertEquals("al-7", server.takeRequest().url.queryParameter("id"))
            while (covers.file(url) == null) Thread.onSpinWait()
            scope.cancel()
        }
    }
}
