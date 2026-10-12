// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.connect

import com.qtekfun.ultimatetunes.core.api.InMemoryServerConfigSource
import com.qtekfun.ultimatetunes.core.api.ServerConfig
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.fake.FakeTunesServer
import com.qtekfun.ultimatetunes.core.api.model.ApiKeySecret
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import okhttp3.HttpUrl.Companion.toHttpUrl
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows

class ConnectionGateTest {
    private val source = InMemoryServerConfigSource()
    private val gate = ConnectionGate(source)
    private val config =
        ServerConfig("https://music.example.net".toHttpUrl(), ApiKeySecret(FakeTunesServer.API_KEY))

    @Test
    fun `the Connect screen shows until a key is kept, also while it is checked`() = runTest {
        assertTrue(gate.needsConnectNow)
        gate.tryConfig(config) {
            assertEquals(config, source.config.value)
            assertTrue(gate.needsConnectNow)
            assertTrue(gate.needsConnect.first())
            TunesResult.Success(Unit)
        }
        assertFalse(gate.needsConnectNow)
        assertFalse(gate.needsConnect.first())
        assertEquals(config, source.config.value)
    }

    @Test
    fun `a failed check restores the previous configuration`() = runTest {
        gate.tryConfig(config) { TunesResult.NotConfigured }
        assertNull(source.config.value)
        assertTrue(gate.needsConnectNow)
    }

    @Test
    fun `a cancelled check restores the previous configuration`() = runTest {
        assertThrows<CancellationException> {
            gate.tryConfig<Unit>(config) { throw CancellationException("left the screen") }
        }
        assertNull(source.config.value)
        assertTrue(gate.needsConnectNow)
    }

    @Test
    fun `disconnect forgets the server`() = runTest {
        source.set(config)
        assertFalse(gate.needsConnectNow)
        gate.disconnect()
        assertNull(source.config.value)
        assertTrue(gate.needsConnect.first())
    }
}
