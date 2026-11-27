// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.navigation

import com.qtekfun.ultimatetunes.core.api.InMemoryServerConfigSource
import com.qtekfun.ultimatetunes.core.api.ServerConfig
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.fake.FakeTunesServer
import com.qtekfun.ultimatetunes.core.api.model.ApiKeySecret
import com.qtekfun.ultimatetunes.ui.FakeAppPrefs
import com.qtekfun.ultimatetunes.ui.FakeCatalogSync
import com.qtekfun.ultimatetunes.ui.FakeOfflineControls
import com.qtekfun.ultimatetunes.ui.MainDispatcherExtension
import com.qtekfun.ultimatetunes.ui.awaitFirst
import com.qtekfun.ultimatetunes.ui.connect.ConnectionGate
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import okhttp3.HttpUrl.Companion.toHttpUrl
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.extension.ExtendWith

@ExtendWith(MainDispatcherExtension::class)
class AppViewModelTest {
    private val source = InMemoryServerConfigSource()
    private val config =
        ServerConfig("https://music.example.net".toHttpUrl(), ApiKeySecret(FakeTunesServer.API_KEY))
    private val catalog = FakeCatalogSync()

    @Test
    fun `a fresh process without a server starts on Connect`() {
        assertTrue(
            AppViewModel(
                ConnectionGate(source),
                FakeAppPrefs(),
                FakeOfflineControls(),
                catalog,
                source
            ).showConnect.value
        )
    }

    @Test
    fun `the root follows the configuration, and reconnect goes back to Connect`() {
        source.set(config)
        val viewModel =
            AppViewModel(
                ConnectionGate(source),
                FakeAppPrefs(),
                FakeOfflineControls(),
                catalog,
                source
            )
        assertFalse(viewModel.showConnect.value)

        viewModel.reconnect()
        assertTrue(viewModel.showConnect.value)

        source.set(config)
        assertFalse(viewModel.showConnect.value)
    }

    @Test
    fun `a connected start finishes a sync the process death left half done`() = runTest {
        source.set(config)
        val offline = FakeOfflineControls()
        AppViewModel(ConnectionGate(source), FakeAppPrefs(), offline, catalog, source)
        assertEquals(listOf("https://music.example.net/"), offline.servers)
    }

    @Test
    fun `a server restored after the start still resumes the sync`() = runTest {
        val offline = FakeOfflineControls()
        AppViewModel(ConnectionGate(source), FakeAppPrefs(), offline, catalog, source)

        source.set(config)

        assertEquals(listOf("https://music.example.net/"), offline.servers)
    }

    @Test
    fun `without a server nothing is resumed`() = runTest {
        val offline = FakeOfflineControls()
        AppViewModel(ConnectionGate(source), FakeAppPrefs(), offline, catalog, source)
        assertTrue(offline.servers.isEmpty())
    }

    @Test
    fun `the catalog syncs on a connected start and again for a new address`() = runTest {
        source.set(config)
        AppViewModel(ConnectionGate(source), FakeAppPrefs(), FakeOfflineControls(), catalog, source)

        source.set(ServerConfig("https://music.lan".toHttpUrl(), config.apiKey))

        assertEquals(listOf("syncIfStale", "syncIfStale"), catalog.calls)
    }

    @Test
    fun `the catalog is cleared when the connection is dropped, not before one exists`() = runTest {
        val viewModel = AppViewModel(
            ConnectionGate(source),
            FakeAppPrefs(),
            FakeOfflineControls(),
            catalog,
            source
        )
        assertTrue(catalog.calls.isEmpty())

        source.set(config)
        viewModel.reconnect()

        assertEquals(listOf("syncIfStale", "clear"), catalog.calls)
    }

    @Test
    fun `a first connection that fails clears nothing`() = runTest {
        val gate = ConnectionGate(source)
        AppViewModel(gate, FakeAppPrefs(), FakeOfflineControls(), catalog, source)

        gate.tryConfig(config) { TunesResult.NotConfigured }

        assertTrue(catalog.calls.isEmpty())
    }

    @Test
    fun `the notification question is asked until answered once`() = runTest {
        val prefs = FakeAppPrefs()
        val viewModel =
            AppViewModel(ConnectionGate(source), prefs, FakeOfflineControls(), catalog, source)
        assertTrue(viewModel.askNotifications.value)

        viewModel.onNotificationsAsked()

        assertFalse(viewModel.askNotifications.awaitFirst { !it })
        assertTrue(prefs.notificationsAsked.first())
    }
}
