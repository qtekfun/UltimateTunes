// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.navigation

import com.qtekfun.ultimatetunes.core.api.InMemoryServerConfigSource
import com.qtekfun.ultimatetunes.core.api.ServerConfig
import com.qtekfun.ultimatetunes.core.api.fake.FakeTunesServer
import com.qtekfun.ultimatetunes.core.api.model.ApiKeySecret
import com.qtekfun.ultimatetunes.ui.MainDispatcherExtension
import com.qtekfun.ultimatetunes.ui.connect.ConnectionGate
import okhttp3.HttpUrl.Companion.toHttpUrl
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.extension.ExtendWith

@ExtendWith(MainDispatcherExtension::class)
class AppViewModelTest {
    private val source = InMemoryServerConfigSource()
    private val config =
        ServerConfig("https://music.example.net".toHttpUrl(), ApiKeySecret(FakeTunesServer.API_KEY))

    @Test
    fun `a fresh process without a server starts on Connect`() {
        assertTrue(AppViewModel(ConnectionGate(source)).showConnect.value)
    }

    @Test
    fun `the root follows the configuration, and reconnect goes back to Connect`() {
        source.set(config)
        val viewModel = AppViewModel(ConnectionGate(source))
        assertFalse(viewModel.showConnect.value)

        viewModel.reconnect()
        assertTrue(viewModel.showConnect.value)

        source.set(config)
        assertFalse(viewModel.showConnect.value)
    }
}
