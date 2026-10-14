// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.localnet

import com.qtekfun.ultimatetunes.core.api.InMemoryServerConfigSource
import com.qtekfun.ultimatetunes.core.api.ServerConfig
import com.qtekfun.ultimatetunes.core.api.model.ApiKeySecret
import com.qtekfun.ultimatetunes.ui.MainDispatcherExtension
import java.net.InetAddress
import kotlinx.coroutines.test.runTest
import okhttp3.HttpUrl.Companion.toHttpUrl
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.extension.ExtendWith

@ExtendWith(MainDispatcherExtension::class)
class LocalNetworkViewModelTest {
    private val source = InMemoryServerConfigSource()
    private var granted = false
    private val answers = mutableMapOf<String, List<String>>()
    private val asked = mutableListOf<String>()
    private val resolver = HostResolver { host ->
        asked += host
        (answers[host] ?: emptyList()).map { InetAddress.getByName(it) }
    }

    private fun viewModel() = LocalNetworkViewModel(source, { granted }, resolver)

    private fun connect(url: String) {
        source.set(ServerConfig(url.toHttpUrl(), ApiKeySecret("utk_" + "x".repeat(43))))
    }

    @Test
    fun `no server, nothing to ask`() {
        val vm = viewModel()
        vm.refresh()
        assertEquals(LocalNetworkState(), vm.state.value)
        assertTrue(asked.isEmpty())
    }

    @Test
    fun `a granted permission never resolves anything`() {
        granted = true
        connect("https://tunes.example.com")
        val vm = viewModel()
        vm.refresh()
        assertEquals(LocalNetworkState(), vm.state.value)
        assertTrue(asked.isEmpty())
    }

    @Test
    fun `a public server needs nothing`() = runTest {
        answers["tunes.example.com"] = listOf("203.0.113.7")
        connect("https://tunes.example.com")
        val vm = viewModel()
        vm.refresh()
        assertFalse(vm.state.value.blocked)
    }

    @Test
    fun `a name that resolves to a LAN address is blocked and explained at once`() = runTest {
        answers["tunes.example.com"] = listOf("2606:4700::1", "192.168.1.6")
        connect("https://tunes.example.com")
        val vm = viewModel()
        vm.refresh()
        assertEquals(LocalNetworkState(blocked = true, showDialog = true), vm.state.value)
    }

    @Test
    fun `a literal LAN address and a dot-local name are blocked without a lookup`() = runTest {
        connect("https://192.168.1.6:8443")
        answers["192.168.1.6"] = listOf("192.168.1.6")
        val literal = viewModel()
        literal.refresh()
        assertTrue(literal.state.value.blocked)

        connect("https://tunes.local")
        val mdns = viewModel()
        mdns.refresh()
        assertTrue(mdns.state.value.blocked)
        assertFalse("tunes.local" in asked)
    }

    @Test
    fun `granting closes it, refusing leads to Settings`() = runTest {
        answers["tunes.example.com"] = listOf("192.168.1.6")
        connect("https://tunes.example.com")
        val vm = viewModel()
        vm.refresh()

        vm.onPermissionResult(granted = false)
        assertEquals(
            LocalNetworkState(blocked = true, showDialog = true, denied = true),
            vm.state.value
        )

        vm.onPermissionResult(granted = true)
        assertEquals(LocalNetworkState(), vm.state.value)
    }

    @Test
    fun `not now closes the dialog, stays dismissed on refresh and can be reopened`() = runTest {
        answers["tunes.example.com"] = listOf("192.168.1.6")
        connect("https://tunes.example.com")
        val vm = viewModel()
        vm.refresh()

        vm.dismiss()
        assertEquals(LocalNetworkState(blocked = true, showDialog = false), vm.state.value)

        vm.refresh()
        assertFalse(vm.state.value.showDialog)
        assertTrue(vm.state.value.blocked)

        vm.reopen()
        assertTrue(vm.state.value.showDialog)
    }

    @Test
    fun `reopen does nothing while nothing is blocked`() {
        val vm = viewModel()
        vm.reopen()
        assertEquals(LocalNetworkState(), vm.state.value)
    }

    @Test
    fun `allowing it in Settings and coming back clears the block`() = runTest {
        answers["tunes.example.com"] = listOf("192.168.1.6")
        connect("https://tunes.example.com")
        val vm = viewModel()
        vm.refresh()
        assertTrue(vm.state.value.blocked)

        granted = true
        vm.refresh()
        assertEquals(LocalNetworkState(), vm.state.value)
    }

    @Test
    fun `moving the server to a public address lifts the block`() = runTest {
        answers["tunes.example.com"] = listOf("192.168.1.6")
        connect("https://tunes.example.com")
        val vm = viewModel()
        vm.refresh()
        assertTrue(vm.state.value.blocked)

        answers["tunes.example.com"] = listOf("203.0.113.7")
        vm.refresh()
        assertEquals(LocalNetworkState(), vm.state.value)
    }
}
