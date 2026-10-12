// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.imports

import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.core.api.ErrorKind
import com.qtekfun.ultimatetunes.core.api.InMemoryServerConfigSource
import com.qtekfun.ultimatetunes.core.api.TunesError
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.fake.FakeTunesServer
import com.qtekfun.ultimatetunes.core.api.model.ImportFileFormat
import com.qtekfun.ultimatetunes.core.api.model.ImportId
import com.qtekfun.ultimatetunes.core.api.model.ImportItemState
import com.qtekfun.ultimatetunes.core.api.model.ImportSource
import com.qtekfun.ultimatetunes.core.api.model.ImportState
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import com.qtekfun.ultimatetunes.ui.MainDispatcherExtension
import com.qtekfun.ultimatetunes.ui.awaitFirst
import com.qtekfun.ultimatetunes.ui.connectedApi
import com.qtekfun.ultimatetunes.ui.dropConnection
import com.qtekfun.ultimatetunes.ui.jsonResponse
import com.qtekfun.ultimatetunes.ui.model.LoadError
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.problem
import java.io.IOException
import kotlinx.coroutines.cancel
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
class ImportViewModelTest {
    private lateinit var server: FakeTunesServer
    private val importId = ImportId("0199d6a2-4c1e-7b3a-9f10-2a6c8e017001")
    private val playlistUrl =
        "https://music.youtube.com/playlist?list=PLx9Kd2Lm4Qp7Wz1Rt5Vb8Nc3Hy6Jf0Ga"

    @BeforeEach
    fun setUp() {
        server = FakeTunesServer().start()
    }

    private val created = mutableListOf<ImportViewModel>()

    @AfterEach
    fun tearDown() {
        // A view model still polling must not resume on Main after the test dispatcher is reset
        // ("Dispatchers.Main is used concurrently"): stop them all first.
        created.forEach { it.viewModelScope.cancel() }
        server.close()
    }

    private fun newViewModel(): ImportViewModel = ImportViewModel(
        connectedApi(server),
        InMemoryServerConfigSource(server.serverConfig())
    ).also { created += it }

    /** A view model whose history and capabilities have loaded (two requests, in this order). */
    private suspend fun viewModel(): ImportViewModel = newViewModel().also { vm ->
        vm.state.awaitFirst { it.history !is LoadState.Loading }
        assertEquals("/ut/v1/imports", server.takeRequest().url.encodedPath)
        assertEquals("/ut/v1/server", server.takeRequest().url.encodedPath)
    }

    private fun csv(text: String, name: String = "mix.csv") =
        PickedFile(name, text.encodeToByteArray())

    @Test
    fun `the history lists earlier imports`() = runTest {
        val state = newViewModel().state.awaitFirst {
            it.history is LoadState.Ready
        }

        val history = (state.history as LoadState.Ready).value
        assertEquals(listOf("Road Trip 2026"), history.map { it.name })
        assertEquals(ImportState.DONE, history.single().state)
        assertEquals("/ut/v1/imports", server.takeRequest().url.encodedPath)
    }

    @Test
    fun `a link import starts, is followed until done and shows its match report`() = runTest {
        val viewModel = viewModel()
        viewModel.onUrlChange(" $playlistUrl ")
        viewModel.onNameChange(" Road Trip ")
        assertTrue(viewModel.state.value.canImportUrl)

        viewModel.importUrl()

        val started = viewModel.state.awaitFirst { it.current != null }
        assertEquals(ImportState.QUEUED, started.current!!.state)
        assertTrue(started.current.inProgress)
        assertEquals("", started.url)
        assertEquals("", started.name)
        val create = server.takeRequest()
        assertEquals("POST", create.method)
        val body = create.body!!.utf8()
        assertTrue(body.contains("\"url\":\"$playlistUrl\""), body)
        assertTrue(body.contains("\"name\":\"Road Trip\""), body)

        val done = viewModel.state.awaitFirst { it.current?.state == ImportState.DONE }.current!!
        assertFalse(done.inProgress)
        assertEquals(PlaylistId("0199d6a2-4c1e-7b3a-9f10-2a6c8e01e001"), done.playlistId)
        assertEquals(3, done.total)
        assertEquals(2, done.matched)
        assertEquals(1, done.notFound)
        assertEquals(
            listOf(ImportItemState.MATCHED, ImportItemState.MATCHED, ImportItemState.NOT_FOUND),
            done.rows.map { it.state }
        )
        assertTrue(done.rows[1].match!!.isExternal)
        assertNull(done.rows[2].match)
        assertEquals("Untitled Demo 4", done.rows[2].title)
        assertEquals("Northbound Static", done.rows[2].artist)
    }

    @Test
    fun `a running import is checked again until it ends`() = runTest {
        server.dispatcher.importExample = "queued"
        val viewModel = viewModel()
        viewModel.open(importId)

        viewModel.state.awaitFirst { it.current?.state == ImportState.QUEUED }
        server.dispatcher.importExample = "done"

        val done = viewModel.state.awaitFirst { it.current?.state == ImportState.DONE }
        assertEquals(3, done.current!!.total)
        // The history, the first check (queued) and at least one more after a pause.
        assertTrue(server.requestCount >= 3)
        viewModel.closeCurrent()
        assertNull(viewModel.state.value.current)
    }

    @Test
    fun `an empty link does nothing and a Spotify link is explained without a request`() = runTest {
        val viewModel = viewModel()
        viewModel.importUrl()
        assertFalse(viewModel.state.value.canImportUrl)

        viewModel.onUrlChange("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M")
        viewModel.importUrl()

        assertEquals(ImportError.SPOTIFY_URL, viewModel.state.value.error)
        assertEquals(2, server.requestCount)
        viewModel.onUrlChange("https://music.youtube.com/playlist?list=x")
        assertNull(viewModel.state.value.error)
    }

    @Test
    fun `a link the server refuses is explained`() = runTest {
        val viewModel = viewModel()
        viewModel.onUrlChange("https://example.net/not-a-playlist")

        viewModel.importUrl()

        val failed = viewModel.state.awaitFirst { it.error != null }
        assertEquals(ImportError.UNSUPPORTED_URL, failed.error)
        assertFalse(failed.submitting)
        assertEquals("https://example.net/not-a-playlist", failed.url)
    }

    @Test
    fun `a picked file guesses its format and uploads with it`() = runTest {
        val viewModel = viewModel()
        assertFalse(viewModel.state.value.canImportFile)
        viewModel.importFile()

        viewModel.onFilePicked(
            csv("Track URI,Track Name,Artist Name(s)\nspotify:track:1,Song,Someone\n")
        )
        assertEquals(ImportFileFormat.EXPORTIFY_CSV, viewModel.state.value.format)
        viewModel.onFormatChange(ImportFileFormat.CSV)
        assertEquals(ImportFileFormat.CSV, viewModel.state.value.format)

        viewModel.importFile()

        val started = viewModel.state.awaitFirst { it.current != null }
        assertEquals(ImportSource.CSV, started.current!!.source)
        assertNull(started.file)
        val upload = server.takeRequest()
        assertTrue(upload.headers["Content-Type"]!!.startsWith("multipart/form-data"))
        val body = upload.body!!.utf8()
        assertTrue(body.contains("filename=\"mix.csv\""), body)
        assertTrue(body.contains("Track URI,Track Name"), body)
    }

    @Test
    fun `a file over 1 MiB is refused before uploading`() = runTest {
        val viewModel = viewModel()

        viewModel.onFilePicked(
            PickedFile("huge.csv", ByteArray(ImportViewModel.MAX_FILE_BYTES + 1))
        )

        assertEquals(ImportError.FILE_TOO_LARGE, viewModel.state.value.error)
        assertNull(viewModel.state.value.file)
        viewModel.onFilePicked(null)
        assertEquals(ImportError.INVALID_FILE, viewModel.state.value.error)
        assertEquals(2, server.requestCount)
    }

    @Test
    fun `a file the server cannot read is explained`() = runTest {
        server.dispatcher.override("ut/v1/imports") { problem(400, "invalid_parameter") }
        val viewModel = newViewModel()
        viewModel.onFilePicked(csv("nothing useful"))

        viewModel.importFile()

        assertEquals(
            ImportError.INVALID_FILE,
            viewModel.state.awaitFirst {
                it.error != null
            }.error
        )
    }

    @Test
    fun `losing the connection while following stops with an error`() = runTest {
        val viewModel = viewModel()
        server.dispatcher.override("ut/v1/imports/${importId.value}") { dropConnection() }

        viewModel.open(importId)

        assertEquals(ImportError.NETWORK, viewModel.state.awaitFirst { it.error != null }.error)
    }

    @Test
    fun `a failed history can be retried`() = runTest {
        server.dispatcher.override("ut/v1/imports") { dropConnection() }
        val viewModel = newViewModel()
        val failed = viewModel.state.awaitFirst { it.history is LoadState.Failed }
        assertEquals(LoadState.Failed(LoadError.NETWORK), failed.history)

        server.dispatcher.clearOverrides()
        viewModel.loadHistory()
        assertTrue(
            viewModel.state.awaitFirst {
                it.history is LoadState.Ready
            }.history is LoadState.Ready
        )
    }

    @Test
    fun `kinds of import the server turned off are not offered`() = runTest {
        server.dispatcher.override("ut/v1/server") {
            jsonResponse(
                """{"name":"UltimateTunes","version":"0.1.0","apiVersion":"1",
                "openSubsonic":{"apiVersion":"1.16.1","extensions":[]},
                "capabilities":{"externalSearch":true,"radio":true,"lyrics":true,
                "youtubeMusicImport":false,"fileImport":true,
                "streamingWhileDownloading":true}}"""
            )
        }
        val state = viewModel().state.awaitFirst { !it.urlImport }

        assertFalse(state.urlImport)
        assertTrue(state.fileImport)
        assertTrue(state.anyImport)
    }

    @Test
    fun `both kinds stay offered when the server cannot say`() = runTest {
        server.dispatcher.override("ut/v1/server") { dropConnection() }
        val state = viewModel().state.value

        assertTrue(state.urlImport)
        assertTrue(state.fileImport)
    }

    @Test
    fun `a progress check the server refuses is a generic server error`() = runTest {
        val viewModel = viewModel()
        server.dispatcher.override("ut/v1/imports/${importId.value}") {
            problem(400, "invalid_parameter")
        }

        viewModel.open(importId)

        assertEquals(ImportError.SERVER, viewModel.state.awaitFirst { it.error != null }.error)
    }

    @Test
    fun `progress check errors never blame the link`() {
        assertEquals(
            ImportError.UNAUTHORIZED,
            ImportViewModel.pollErrorOf(TunesResult.NotConfigured)
        )
        assertEquals(
            ImportError.SERVER,
            ImportViewModel.pollErrorOf(
                TunesResult.ApiError(TunesError(ErrorKind.UNSUPPORTED_URL), 400)
            )
        )
    }

    @Nested
    inner class GuessFormat {
        private fun guess(name: String, text: String) =
            ImportViewModel.guessFormat(name, text.encodeToByteArray())

        @Test
        fun `JSON by name or content is a Spotify data export`() {
            assertEquals(ImportFileFormat.SPOTIFY_JSON, guess("Playlist1.json", ""))
            assertEquals(
                ImportFileFormat.SPOTIFY_JSON,
                guess("export", "\uFEFF  {\"playlists\":[]}")
            )
            assertEquals(ImportFileFormat.SPOTIFY_JSON, guess("export.txt", "[{}]"))
        }

        @Test
        fun `Exportify columns make an Exportify CSV`() {
            assertEquals(
                ImportFileFormat.EXPORTIFY_CSV,
                guess("a.csv", "\"Track URI\",\"Track Name\"\n")
            )
            assertEquals(
                ImportFileFormat.EXPORTIFY_CSV,
                guess("a.csv", "Track Name,Artist Name(s)\n")
            )
        }

        @Test
        fun `anything else is the generic CSV`() {
            assertEquals(ImportFileFormat.CSV, guess("a.csv", "title,artist,album\nA,B,C\n"))
            assertEquals(ImportFileFormat.CSV, guess("a.csv", ""))
        }
    }

    @Nested
    inner class Errors {
        private fun api(kind: ErrorKind) = TunesResult.ApiError(TunesError(kind), 400)

        @Test
        fun `server errors are explained by kind`() {
            assertEquals(
                ImportError.UNSUPPORTED_URL,
                ImportViewModel.errorOf(api(ErrorKind.UNSUPPORTED_URL), true)
            )
            assertEquals(
                ImportError.FILE_TOO_LARGE,
                ImportViewModel.errorOf(api(ErrorKind.PAYLOAD_TOO_LARGE), true)
            )
            assertEquals(
                ImportError.INVALID_FILE,
                ImportViewModel.errorOf(api(ErrorKind.MISSING_PARAMETER), true)
            )
            assertEquals(
                ImportError.UNSUPPORTED_URL,
                ImportViewModel.errorOf(api(ErrorKind.INVALID_PARAMETER), false)
            )
            assertEquals(
                ImportError.DISABLED,
                ImportViewModel.errorOf(api(ErrorKind.FEATURE_DISABLED), false)
            )
            assertEquals(
                ImportError.RATE_LIMITED,
                ImportViewModel.errorOf(api(ErrorKind.RATE_LIMITED), false)
            )
            assertEquals(
                ImportError.SERVER,
                ImportViewModel.errorOf(api(ErrorKind.INTERNAL), false)
            )
        }

        @Test
        fun `transport and credential failures`() {
            assertEquals(
                ImportError.NETWORK,
                ImportViewModel.errorOf(TunesResult.NetworkError(IOException()), false)
            )
            assertEquals(
                ImportError.UNAUTHORIZED,
                ImportViewModel.errorOf(TunesResult.NotConfigured, false)
            )
            assertEquals(
                ImportError.UNAUTHORIZED,
                ImportViewModel.errorOf(
                    TunesResult.Unauthorized(TunesError(ErrorKind.INVALID_API_KEY), 401),
                    false
                )
            )
            assertEquals(
                ImportError.SERVER,
                ImportViewModel.errorOf(TunesResult.ProtocolError("x", 200), false)
            )
        }
    }
}
