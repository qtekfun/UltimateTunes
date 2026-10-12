// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.lyrics

import com.qtekfun.ultimatetunes.core.api.fake.FakeTunesServer
import com.qtekfun.ultimatetunes.core.api.model.LyricLine
import com.qtekfun.ultimatetunes.core.api.model.Lyrics
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.ui.MainDispatcherExtension
import com.qtekfun.ultimatetunes.ui.awaitFirst
import com.qtekfun.ultimatetunes.ui.connectedApi
import com.qtekfun.ultimatetunes.ui.dropConnection
import com.qtekfun.ultimatetunes.ui.model.LoadError
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.subsonicOk
import kotlinx.coroutines.test.runTest
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Nested
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.extension.ExtendWith

@ExtendWith(MainDispatcherExtension::class)
class LyricsViewModelTest {
    private lateinit var server: FakeTunesServer
    private val song = SongId("0199d6a2-4c1e-7b3a-9f10-2a6c8e01c001")

    @BeforeEach
    fun setUp() {
        server = FakeTunesServer().start()
    }

    @AfterEach
    fun tearDown() {
        server.close()
    }

    private suspend fun LyricsViewModel.loaded(): LyricsUiState =
        state.awaitFirst { it.content !is LoadState.Loading }

    @Test
    fun `nothing loads until the lyrics are shown`() {
        LyricsViewModel(connectedApi(server))
        assertEquals(0, server.requestCount)
    }

    @Test
    fun `synced lyrics of the song playing, with their times`() = runTest {
        val viewModel = LyricsViewModel(connectedApi(server))
        viewModel.show(song)

        val state = viewModel.loaded()
        assertEquals(song, state.songId)
        val lyrics = (state.content as LoadState.Ready).value!!
        assertTrue(lyrics.synced)
        assertEquals(listOf(0L, 4210L, 9875L), lyrics.lines.map { it.startMillis })
        assertEquals("Salt on the window, the night coming in", lyrics.lines.first().text)
        assertEquals(song.value, server.takeRequest().url.queryParameter("id"))
    }

    @Test
    fun `showing the same song again does not reload, another song does`() = runTest {
        val viewModel = LyricsViewModel(connectedApi(server))
        viewModel.show(song)
        viewModel.loaded()
        viewModel.show(song)
        assertEquals(1, server.requestCount)

        val other = SongId("yt:Qx7Lm2pZ0aB")
        viewModel.show(other)
        assertEquals(
            other,
            viewModel.state.awaitFirst {
                it.songId == other &&
                    it.content is LoadState.Ready
            }.songId
        )
        assertEquals(2, server.requestCount)
    }

    @Test
    fun `a song without lyrics says so`() = runTest {
        server.dispatcher.override("rest/getLyricsBySongId") { subsonicOk("lyricsList", "{}") }
        val viewModel = LyricsViewModel(connectedApi(server))
        viewModel.show(song)

        assertEquals(LoadState.Ready(null), viewModel.loaded().content)
    }

    @Test
    fun `a failure can be retried, and showing it again retries too`() = runTest {
        server.dispatcher.override("rest/getLyricsBySongId") { dropConnection() }
        val viewModel = LyricsViewModel(connectedApi(server))
        viewModel.retry()
        assertEquals(0, server.requestCount)

        viewModel.show(song)
        assertEquals(LoadState.Failed(LoadError.NETWORK), viewModel.loaded().content)

        viewModel.show(song)
        assertEquals(LoadState.Loading, viewModel.state.value.content)
        assertEquals(LoadState.Failed(LoadError.NETWORK), viewModel.loaded().content)
        assertEquals(2, server.requestCount)

        server.dispatcher.clearOverrides()
        viewModel.retry()
        assertTrue(
            viewModel.state.awaitFirst {
                it.content is LoadState.Ready
            }.content is LoadState.Ready
        )
    }

    @Nested
    inner class Pick {
        private fun lyrics(
            synced: Boolean,
            vararg lines: Pair<String, Double?>,
            offset: Double? = null
        ) = Lyrics(
            lang = "und",
            synced = synced,
            line = lines.map { (text, start) -> LyricLine(text, start) },
            offset = offset
        )

        @Test
        fun `synced lyrics win over plain ones, whatever the order`() {
            val picked = LyricsViewModel.pick(
                listOf(lyrics(false, "plain" to null), lyrics(true, "synced" to 1000.0))
            )!!
            assertTrue(picked.synced)
            assertEquals("synced", picked.lines.single().text)
        }

        @Test
        fun `plain lyrics have no times`() {
            val picked = LyricsViewModel.pick(listOf(lyrics(false, "a" to null, "b" to 5.0)))!!
            assertFalse(picked.synced)
            assertEquals(listOf(null, null), picked.lines.map { it.startMillis })
        }

        @Test
        fun `a positive offset shows the lines sooner`() {
            val picked = LyricsViewModel.pick(
                listOf(lyrics(true, "a" to 1000.0, "b" to 3000.0, offset = 500.0))
            )!!
            assertEquals(listOf(500L, 2500L), picked.lines.map { it.startMillis })
        }

        @Test
        fun `empty lyrics count as none`() {
            assertNull(LyricsViewModel.pick(emptyList()))
            assertNull(LyricsViewModel.pick(listOf(lyrics(true), lyrics(false))))
        }
    }

    @Nested
    inner class ActiveLine {
        private val lines = listOf(
            LyricLineUi("one", 0),
            LyricLineUi("two", 4210),
            LyricLineUi("three", 9875)
        )

        @Test
        fun `the active line is the last one that started`() {
            assertEquals(0, LyricsViewModel.activeLine(lines, 0))
            assertEquals(0, LyricsViewModel.activeLine(lines, 4209))
            assertEquals(1, LyricsViewModel.activeLine(lines, 4210))
            assertEquals(2, LyricsViewModel.activeLine(lines, 600_000))
        }

        @Test
        fun `before the first line, and in plain lyrics, no line is active`() {
            assertEquals(-1, LyricsViewModel.activeLine(listOf(LyricLineUi("late", 2000)), 1000))
            assertEquals(-1, LyricsViewModel.activeLine(listOf(LyricLineUi("plain", null)), 1000))
        }
    }
}
