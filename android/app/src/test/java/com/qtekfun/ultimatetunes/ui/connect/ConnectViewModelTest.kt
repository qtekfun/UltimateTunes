// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.connect

import com.qtekfun.ultimatetunes.core.api.InMemoryServerConfigSource
import com.qtekfun.ultimatetunes.core.api.ServerConfig
import com.qtekfun.ultimatetunes.core.api.fake.ContractFixtures
import com.qtekfun.ultimatetunes.core.api.fake.FakeTunesServer
import com.qtekfun.ultimatetunes.ui.MainDispatcherExtension
import com.qtekfun.ultimatetunes.ui.apiWith
import com.qtekfun.ultimatetunes.ui.awaitFirst
import java.util.Optional
import kotlinx.coroutines.test.runTest
import mockwebserver3.MockResponse
import okhttp3.Headers.Companion.headersOf
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
class ConnectViewModelTest {
    private lateinit var server: FakeTunesServer
    private lateinit var source: InMemoryServerConfigSource
    private lateinit var gate: ConnectionGate
    private lateinit var viewModel: ConnectViewModel

    @BeforeEach
    fun setUp() {
        server = FakeTunesServer().start()
        source = InMemoryServerConfigSource()
        gate = ConnectionGate(source)
        viewModel = ConnectViewModel(apiWith(source), gate, CleartextPolicy { true })
    }

    @AfterEach
    fun tearDown() {
        server.close()
    }

    private fun enter(
        url: String = server.baseUrl.toString(),
        key: String = FakeTunesServer.API_KEY
    ) {
        viewModel.onServerUrlChange(url)
        viewModel.onApiKeyChange(key)
    }

    private suspend fun connectAndWait(): ConnectUiState {
        viewModel.connect()
        return viewModel.state.awaitFirst { !it.checking }
    }

    @Test
    fun `a working server and key connect and are kept`() = runTest {
        enter(key = "  ${FakeTunesServer.API_KEY}  ")

        val state = connectAndWait()

        assertEquals("UltimateTunes", state.connectedTo)
        assertNull(state.error)
        val config = source.config.value
        assertEquals(server.baseUrl, config?.root)
        assertEquals(FakeTunesServer.API_KEY, config?.apiKey?.value)
    }

    @Test
    fun `connecting clears what was typed, and going back to Connect starts over`() = runTest {
        enter()

        val connected = connectAndWait()

        assertEquals("", connected.serverUrl)
        assertEquals("", connected.apiKey)
        assertEquals("UltimateTunes", connected.connectedTo)

        gate.disconnect()

        // The reset runs on the view model's own collector: wait for it, do not race it.
        assertEquals(ConnectUiState(), viewModel.state.awaitFirst { it == ConnectUiState() })
    }

    @Test
    fun `a failed check keeps what was typed and is not a reconnect`() = runTest {
        enter(key = "utk_" + "B".repeat(43))

        val state = connectAndWait()

        assertEquals(server.baseUrl.toString(), state.serverUrl)
        assertEquals("utk_" + "B".repeat(43), state.apiKey)
        assertEquals(ConnectError.KEY_REFUSED, state.error)
    }

    @Test
    fun `a refused key is reported and not kept`() = runTest {
        enter(key = "utk_" + "A".repeat(43))

        val state = connectAndWait()

        assertEquals(ConnectError.KEY_REFUSED, state.error)
        assertNull(state.connectedTo)
        assertNull(source.config.value)
    }

    @Test
    fun `an address where nothing answers is unreachable`() = runTest {
        val url = server.baseUrl.toString()
        server.close()
        enter(url = url)

        assertEquals(ConnectError.UNREACHABLE, connectAndWait().error)
        assertNull(source.config.value)
    }

    @Test
    fun `something that is not an UltimateTunes server is recognised`() = runTest {
        server.dispatcher.override("ut/v1/server") {
            MockResponse(
                code = 404,
                headers = headersOf("Content-Type", "text/html"),
                body = "<html/>"
            )
        }
        enter()

        assertEquals(ConnectError.NOT_A_SERVER, connectAndWait().error)
    }

    @Test
    fun `a server error while checking the address is reported`() = runTest {
        server.dispatcher.override("ut/v1/server") {
            MockResponse(
                code = 500,
                headers = headersOf("Content-Type", "application/problem+json"),
                body = ContractFixtures.utV1("response.Internal")
            )
        }
        enter()

        assertEquals(ConnectError.SERVER_ERROR, connectAndWait().error)
    }

    @Test
    fun `a server error while checking the key restores the previous configuration`() = runTest {
        server.dispatcher.override("ut/v1/me") {
            MockResponse(
                code = 500,
                headers = headersOf("Content-Type", "application/problem+json"),
                body = ContractFixtures.utV1("response.Internal")
            )
        }
        enter()

        assertEquals(ConnectError.SERVER_ERROR, connectAndWait().error)
        assertNull(source.config.value)
    }

    @Test
    fun `the connection dropping while checking the key is unreachable`() = runTest {
        server.dispatcher.override("ut/v1/me") {
            MockResponse.Builder().onResponseStart(
                mockwebserver3.SocketEffect.CloseSocket()
            ).build()
        }
        enter()

        assertEquals(ConnectError.UNREACHABLE, connectAndWait().error)
    }

    @Test
    fun `a malformed address is refused without asking the server`() = runTest {
        enter(url = "not a url")

        viewModel.connect()

        assertEquals(ConnectError.INVALID_URL, viewModel.state.value.error)
        assertEquals(0, server.requestCount)
    }

    @Test
    fun `plain http is refused where the network security config forbids it`() = runTest {
        val strict = ConnectViewModel(
            apiWith(source),
            ConnectionGate(source),
            cleartext = { host -> host == "10.0.2.2" }
        )
        strict.onServerUrlChange("http://music.example.net")
        strict.onApiKeyChange(FakeTunesServer.API_KEY)

        strict.connect()

        assertEquals(ConnectError.INSECURE_URL, strict.state.value.error)
        assertEquals(0, server.requestCount)

        // The emulator's host may use http in debug builds; https is always fine.
        strict.onServerUrlChange("https://music.example.net")
        assertNull(strict.state.value.error)
    }

    @Test
    fun `release builds have no demo`() {
        assertNull(viewModel.demoLabelRes)

        viewModel.tryDemo()

        assertFalse(viewModel.state.value.checking)
        assertEquals(0, server.requestCount)
    }

    @Test
    fun `the demo connects to its server through the normal checks`() = runTest {
        val demo = object : DemoServer {
            override val labelRes: Int = DEMO_LABEL

            override suspend fun start() = server.serverConfig()
        }
        val withDemo = ConnectViewModel(
            apiWith(source),
            ConnectionGate(source),
            CleartextPolicy { true },
            Optional.of(demo)
        )
        assertEquals(DEMO_LABEL, withDemo.demoLabelRes)

        withDemo.tryDemo()
        val state = withDemo.state.awaitFirst { !it.checking }

        assertEquals("UltimateTunes", state.connectedTo)
        assertEquals(server.baseUrl, source.config.value?.root)
        assertEquals("", state.serverUrl)
    }

    @Test
    fun `a demo server that does not start is reported as unreachable`() = runTest {
        val demo = object : DemoServer {
            override val labelRes: Int = DEMO_LABEL

            override suspend fun start(): ServerConfig? = null
        }
        val withDemo = ConnectViewModel(
            apiWith(source),
            ConnectionGate(source),
            CleartextPolicy { true },
            Optional.of(demo)
        )

        withDemo.tryDemo()
        val state = withDemo.state.awaitFirst { !it.checking }

        assertEquals(ConnectError.UNREACHABLE, state.error)
        assertNull(source.config.value)
    }

    @Test
    fun `the state never prints the key`() {
        enter()
        val text = viewModel.state.value.toString()
        assertFalse(FakeTunesServer.API_KEY in text, text)
        assertTrue("apiKey=redacted" in text, text)
    }

    @Test
    fun `a key of the wrong shape is refused without asking the server`() = runTest {
        enter(key = "secret")

        viewModel.connect()

        assertEquals(ConnectError.INVALID_KEY, viewModel.state.value.error)
        assertEquals(0, server.requestCount)
    }

    @Test
    fun `editing a field clears the error`() {
        enter(key = "secret")
        viewModel.connect()

        viewModel.onApiKeyChange("utk_")
        assertNull(viewModel.state.value.error)

        viewModel.connect()
        viewModel.onServerUrlChange("music.example.net")
        assertNull(viewModel.state.value.error)
    }

    @Test
    fun `connect is offered only with both fields filled`() {
        assertFalse(viewModel.state.value.canConnect)
        viewModel.onServerUrlChange("music.example.net")
        assertFalse(viewModel.state.value.canConnect)
        viewModel.onApiKeyChange("utk_x")
        assertTrue(viewModel.state.value.canConnect)
        assertFalse(ConnectUiState(serverUrl = "a", apiKey = "b", checking = true).canConnect)
    }

    @Test
    fun `a second connect while checking is ignored`() = runTest {
        server.dispatcher.override("ut/v1/server") {
            MockResponse.Builder()
                .code(200)
                .headers(headersOf("Content-Type", "application/json"))
                .body(ContractFixtures.utV1("getServerInfo.200"))
                .headersDelay(300, java.util.concurrent.TimeUnit.MILLISECONDS)
                .build()
        }
        enter()

        viewModel.connect()
        assertTrue(viewModel.state.value.checking)
        viewModel.connect()

        assertEquals("UltimateTunes", viewModel.state.awaitFirst { !it.checking }.connectedTo)
        // One server check and one key check: the second tap sent nothing.
        assertEquals(2, server.requestCount)
    }

    @Nested
    inner class NormalizeServerUrl {
        private fun normalize(input: String) =
            ConnectViewModel.normalizeServerUrl(input)?.toString()

        @Test
        fun `adds https when no scheme is given`() {
            assertEquals("https://music.example.net/", normalize("music.example.net"))
        }

        @Test
        fun `keeps http, ports and path prefixes, adding the trailing slash`() {
            assertEquals("http://10.0.2.2:8044/", normalize("http://10.0.2.2:8044"))
            assertEquals("https://example.net/tunes/", normalize(" https://example.net/tunes "))
        }

        @Test
        fun `drops query and fragment`() {
            assertEquals("https://example.net/", normalize("https://example.net/?apiKey=x#top"))
        }

        @Test
        fun `refuses what is not an http address`() {
            assertNull(normalize(""))
            assertNull(normalize("   "))
            assertNull(normalize("music example net"))
            assertNull(normalize("ftp://example.net"))
            assertNull(normalize("https://"))
        }
    }

    private companion object {
        const val DEMO_LABEL = 42
    }
}
