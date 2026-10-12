// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.connect

import com.qtekfun.ultimatetunes.core.api.InMemoryServerConfigSource
import com.qtekfun.ultimatetunes.core.api.ServerConfig
import com.qtekfun.ultimatetunes.core.api.fake.FakeTunesServer
import com.qtekfun.ultimatetunes.core.api.model.ApiKeySecret
import com.qtekfun.ultimatetunes.ui.MainDispatcherExtension
import com.qtekfun.ultimatetunes.ui.apiWith
import com.qtekfun.ultimatetunes.ui.awaitFirst
import java.net.URLEncoder
import kotlinx.coroutines.test.runTest
import okhttp3.HttpUrl.Companion.toHttpUrl
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.extension.ExtendWith

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
        // The fake server is plain http on localhost, as debug builds allow for the emulator.
        viewModel = ConnectLinkViewModel(apiWith(source), gate, CleartextPolicy { true }, inbox)
    }

    @AfterEach
    fun tearDown() {
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

    private suspend fun confirmAndWait(): ConnectLinkUiState {
        viewModel.confirm()
        return viewModel.state.awaitFirst { (it as? ConnectLinkUiState.Confirm)?.checking != true }
    }

    @Test
    fun `a link asks first, without contacting the server or keeping it in the inbox`() {
        open()

        val state = viewModel.state.value as ConnectLinkUiState.Confirm
        assertEquals(server.baseUrl.toString(), state.serverUrl)
        assertEquals(server.baseUrl.host, state.host)
        assertFalse(state.replacing)
        assertFalse(state.checking)
        assertNull(inbox.pending.value)
        assertEquals(0, server.requestCount)
        assertFalse(FakeTunesServer.API_KEY in state.toString())
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
    fun `cancelling discards the link and changes nothing`() {
        open()

        viewModel.dismiss()
        viewModel.confirm()

        assertEquals(ConnectLinkUiState.Idle, viewModel.state.value)
        assertNull(source.config.value)
        assertEquals(0, server.requestCount)
    }

    @Test
    fun `when connected, the dialog says it replaces the current server`() {
        source.set(previous)

        open()

        assertEquals(true, (viewModel.state.value as ConnectLinkUiState.Confirm).replacing)
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
    fun `a new link replaces one still waiting for an answer`() {
        open(key = unknownKey)
        inbox.offer("ultimatetunes://elsewhere")

        assertEquals(
            ConnectLinkUiState.Refused(ConnectLinkError.MALFORMED),
            viewModel.state.value
        )
        viewModel.confirm()
        assertEquals(0, server.requestCount)
    }
}
