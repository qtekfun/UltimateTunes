// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.connect

import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.core.api.InMemoryServerConfigSource
import com.qtekfun.ultimatetunes.core.api.ServerConfig
import com.qtekfun.ultimatetunes.core.api.fake.ContractFixtures
import com.qtekfun.ultimatetunes.core.api.fake.FakeTunesServer
import com.qtekfun.ultimatetunes.core.api.model.ApiKeySecret
import com.qtekfun.ultimatetunes.ui.MainDispatcherExtension
import com.qtekfun.ultimatetunes.ui.apiWith
import com.qtekfun.ultimatetunes.ui.awaitFirst
import com.qtekfun.ultimatetunes.ui.closeForTest
import java.net.URLEncoder
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import mockwebserver3.MockResponse
import okhttp3.Headers.Companion.headersOf
import okhttp3.HttpUrl.Companion.toHttpUrl
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.extension.ExtendWith

@OptIn(ExperimentalCoroutinesApi::class)
@ExtendWith(MainDispatcherExtension::class)
class ConnectLinkViewModelTest {
    private lateinit var server: FakeTunesServer
    private lateinit var source: InMemoryServerConfigSource
    private lateinit var gate: ConnectionGate
    private lateinit var inbox: ConnectLinkInbox
    private lateinit var viewModel: ConnectLinkViewModel

    /** A well-formed key the fake server does not know, built at run time. */
    private val unknownKey = "utk_" + "Q".repeat(43)

    @BeforeEach
    fun setUp() {
        server = FakeTunesServer().start()
        source = InMemoryServerConfigSource()
        gate = ConnectionGate(source)
        inbox = ConnectLinkInbox()
        viewModel = newViewModel()
        // As the dialog's route does while the screen is started.
        viewModel.viewModelScope.launch { viewModel.receiveLinks() }
    }

    // The fake server is plain http on localhost, as debug builds allow for the emulator.
    private fun newViewModel() =
        ConnectLinkViewModel(apiWith(source), gate, CleartextPolicy { true }, inbox)

    @AfterEach
    fun tearDown() {
        viewModel.closeForTest()
        server.close()
    }

    private fun encode(value: String) = URLEncoder.encode(value, "UTF-8")

    private fun open(
        url: String = server.baseUrl.toString().removeSuffix("/"),
        key: String = FakeTunesServer.API_KEY
    ) = inbox.offer("ultimatetunes://connect?url=${encode(url)}&key=${encode(key)}")

    private val previous by lazy {
        ServerConfig("https://old.example.net/".toHttpUrl(), ApiKeySecret("utk_" + "P".repeat(43)))
    }

    private val confirmShown get() = viewModel.state.value as ConnectLinkUiState.Confirm

    /** Waits until Connect works (the dialog has been on screen long enough). */
    private fun TestScope.armed() {
        advanceTimeBy(ConnectLinkViewModel.ARM_DELAY_MS + 1)
        runCurrent()
        assertTrue(confirmShown.armed)
    }

    private suspend fun TestScope.confirmAndWait(): ConnectLinkUiState {
        armed()
        viewModel.confirm()
        return viewModel.state.awaitFirst { (it as? ConnectLinkUiState.Confirm)?.checking != true }
    }

    @Test
    fun `a link asks first, without contacting the server or keeping it in the inbox`() {
        open()

        val state = confirmShown
        assertEquals(server.baseUrl.toString(), state.serverUrl)
        assertEquals(server.baseUrl.host, state.host)
        assertFalse(state.replacing)
        assertFalse(state.checking)
        assertFalse(state.anotherLinkIgnored)
        assertNull(inbox.pending.value)
        assertEquals(0, server.requestCount)
        assertFalse(FakeTunesServer.API_KEY in state.toString())
    }

    @Test
    fun `Connect does nothing until the dialog has been shown for a moment`() = runTest {
        open()

        viewModel.confirm()
        assertFalse(confirmShown.canConfirm)
        assertFalse(confirmShown.checking)
        advanceTimeBy(ConnectLinkViewModel.ARM_DELAY_MS - 1)
        runCurrent()
        viewModel.confirm()

        assertFalse(confirmShown.checking)
        assertEquals(0, server.requestCount)
        armed()
        assertTrue(confirmShown.canConfirm)
    }

    @Test
    fun `confirming runs the Connect checks and keeps the server`() = runTest {
        open()

        assertEquals(ConnectLinkUiState.Idle, confirmAndWait())

        assertEquals(server.baseUrl, source.config.value?.root)
        assertEquals(FakeTunesServer.API_KEY, source.config.value?.apiKey?.value)
        assertFalse(gate.needsConnectNow)
    }

    @Test
    fun `cancelling discards the link and changes nothing`() = runTest {
        open()

        viewModel.dismiss()
        advanceTimeBy(ConnectLinkViewModel.ARM_DELAY_MS + 1)
        runCurrent()
        viewModel.confirm()

        assertEquals(ConnectLinkUiState.Idle, viewModel.state.value)
        assertNull(source.config.value)
        assertEquals(0, server.requestCount)
    }

    @Test
    fun `when connected, the dialog says it replaces the current server`() {
        source.set(previous)

        open()

        assertTrue(confirmShown.replacing)
    }

    @Test
    fun `a replacement whose key is refused keeps the current server`() = runTest {
        source.set(previous)
        open(key = unknownKey)

        val state = confirmAndWait() as ConnectLinkUiState.Confirm

        assertEquals(ConnectError.KEY_REFUSED, state.error)
        assertEquals(previous, source.config.value)
        assertFalse(gate.needsConnectNow)

        viewModel.dismiss()
        assertEquals(ConnectLinkUiState.Idle, viewModel.state.value)
        assertEquals(previous, source.config.value)
    }

    @Test
    fun `a replacement where nothing answers never touches the current server`() = runTest {
        source.set(previous)
        val url = server.baseUrl.toString()
        server.close()
        open(url = url)

        val state = confirmAndWait() as ConnectLinkUiState.Confirm

        assertEquals(ConnectError.UNREACHABLE, state.error)
        assertEquals(previous, source.config.value)
    }

    @Test
    fun `a replacement that works takes over only then`() = runTest {
        source.set(previous)
        open()

        assertEquals(ConnectLinkUiState.Idle, confirmAndWait())

        assertEquals(server.baseUrl, source.config.value?.root)
    }

    @Test
    fun `a bad link is refused with its reason and closes without changes`() {
        source.set(previous)

        open(url = "http://music.example.net", key = "utk_short")

        assertEquals(
            ConnectLinkUiState.Refused(ConnectLinkError.INVALID_KEY),
            viewModel.state.value
        )
        viewModel.confirm()
        viewModel.dismiss()
        assertEquals(ConnectLinkUiState.Idle, viewModel.state.value)
        assertEquals(previous, source.config.value)
        assertEquals(0, server.requestCount)
    }

    @Test
    fun `a link arriving while one is shown is ignored, and the dialog says so`() = runTest {
        open()
        armed()
        val first = confirmShown

        open(url = "https://evil.example.net", key = unknownKey)

        // Same link, a notice added, and Connect waits again since the buttons moved.
        assertEquals(first.copy(anotherLinkIgnored = true, armed = false), confirmShown)
        assertNull(inbox.pending.value)
        viewModel.confirm()
        assertFalse(confirmShown.checking)
        assertEquals(0, server.requestCount)
        assertEquals(ConnectLinkUiState.Idle, confirmAndWait())
        assertEquals(server.baseUrl, source.config.value?.root)
    }

    @Test
    fun `a link arriving over a refusal is ignored too`() {
        inbox.offer("ultimatetunes://elsewhere")

        open()

        assertEquals(
            ConnectLinkUiState.Refused(ConnectLinkError.MALFORMED, anotherLinkIgnored = true),
            viewModel.state.value
        )
    }

    @Test
    fun `a link arriving during the check is reported as ignored, not dropped silently`() =
        runTest {
            server.dispatcher.override("ut/v1/me") {
                MockResponse.Builder()
                    .code(500)
                    .headers(headersOf("Content-Type", "application/problem+json"))
                    .body(ContractFixtures.utV1("response.Internal"))
                    .headersDelay(300, TimeUnit.MILLISECONDS)
                    .build()
            }
            open()
            armed()
            viewModel.confirm()

            open(key = unknownKey)

            assertTrue(confirmShown.checking)
            assertTrue(confirmShown.anotherLinkIgnored)
            val done = viewModel.state.awaitFirst {
                (it as? ConnectLinkUiState.Confirm)?.checking == false
            } as ConnectLinkUiState.Confirm
            assertEquals(ConnectError.SERVER_ERROR, done.error)
            assertNull(source.config.value)
        }

    @Test
    fun `links wait in the inbox while the screen is not started`() {
        val stopped = newViewModel()
        try {
            viewModel.closeForTest() // the default one would take it
            open()

            assertEquals(ConnectLinkUiState.Idle, stopped.state.value)
            assertNotNull(inbox.pending.value)

            stopped.viewModelScope.launch { stopped.receiveLinks() }
            assertTrue(stopped.state.value is ConnectLinkUiState.Confirm)
            assertNull(inbox.pending.value)
        } finally {
            stopped.closeForTest()
        }
    }
}
