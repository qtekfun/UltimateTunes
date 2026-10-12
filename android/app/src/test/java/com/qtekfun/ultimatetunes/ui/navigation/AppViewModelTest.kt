// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.navigation

import com.qtekfun.ultimatetunes.core.api.InMemoryServerConfigSource
import com.qtekfun.ultimatetunes.core.api.ServerConfig
import com.qtekfun.ultimatetunes.core.api.fake.FakeTunesServer
import com.qtekfun.ultimatetunes.core.api.model.ApiKeySecret
import okhttp3.HttpUrl.Companion.toHttpUrl
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class AppViewModelTest {
    @Test
    fun `starts on Connect until a server is configured`() {
        val source = InMemoryServerConfigSource()
        val viewModel = AppViewModel(source)
        assertFalse(viewModel.isConfigured)

        source.set(
            ServerConfig(
                "https://music.example.net".toHttpUrl(),
                ApiKeySecret(FakeTunesServer.API_KEY)
            )
        )
        assertTrue(viewModel.isConfigured)
    }
}
