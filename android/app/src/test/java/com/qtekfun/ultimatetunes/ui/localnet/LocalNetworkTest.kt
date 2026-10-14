// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.localnet

import java.net.InetAddress
import kotlinx.coroutines.test.runTest
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class LocalNetworkTest {
    private fun local(literal: String) = LocalNetwork.isLocal(InetAddress.getByName(literal))

    @Test
    fun `private IPv4 ranges are local`() {
        listOf(
            "10.0.0.1", "10.255.255.254", "172.16.0.1", "172.31.255.254", "192.168.1.1",
            "192.168.88.6", "169.254.1.1", "100.64.0.1", "100.127.255.254"
        ).forEach { assertTrue(local(it), it) }
    }

    @Test
    fun `public, loopback, wildcard and multicast IPv4 are not local`() {
        listOf(
            "8.8.8.8", "1.1.1.1", "172.15.255.255", "172.32.0.1", "100.63.255.255",
            "100.128.0.1", "192.167.1.1", "192.169.0.1", "169.253.1.1", "127.0.0.1",
            "0.0.0.0", "224.0.0.1", "203.0.113.7"
        ).forEach { assertFalse(local(it), it) }
    }

    @Test
    fun `IPv6 unique local and link-local are local, global and loopback are not`() {
        listOf("fd00::1", "fc00::1", "fdff:ffff::1", "fe80::1", "febf::1")
            .forEach { assertTrue(local(it), it) }
        listOf("2606:4700:3037::ac43:d330", "2001:db8::1", "::1", "::", "ff02::1", "fec0::1")
            .forEach { assertFalse(local(it), it) }
    }

    @Test
    fun `an IPv4-mapped IPv6 address is judged by the IPv4 address inside`() {
        assertTrue(local("::ffff:192.168.1.5"))
        assertTrue(local("::ffff:10.0.0.1"))
        assertFalse(local("::ffff:8.8.8.8"))
    }

    @Test
    fun `the permission is the Android 17 one`() {
        assertEquals("android.permission.ACCESS_LOCAL_NETWORK", LocalNetwork.PERMISSION)
        assertEquals(37, LocalNetwork.FIRST_SDK)
    }

    @Test
    fun `the system resolver answers a literal address without any lookup`() = runTest {
        val resolver = SystemHostResolver(timeoutMs = 2_000)
        assertEquals(listOf("192.168.1.9"), resolver.resolve("192.168.1.9").map { it.hostAddress })
    }

    @Test
    fun `an unknown host resolves to nothing instead of failing`() = runTest {
        assertTrue(SystemHostResolver(timeoutMs = 2_000).resolve("no-such-host.invalid").isEmpty())
    }
}
