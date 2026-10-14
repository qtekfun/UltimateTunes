// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.localnet

import java.net.InetAddress
import java.net.UnknownHostException
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull

/**
 * Android 17 (API 37) blocks an app that targets SDK 37 from opening connections to the local
 * network unless it holds `ACCESS_LOCAL_NETWORK` (permission group "Nearby devices"). The check
 * is on the destination ADDRESS, so a host name that your DNS maps to `192.168.x.x` (split DNS at
 * home) is blocked too, and the failure looks like an endless timeout. This file decides which
 * addresses count, so the app can ask for the permission only when it is really needed.
 */
object LocalNetwork {
    /** The permission, written out so this file builds on every compile SDK. */
    const val PERMISSION = "android.permission.ACCESS_LOCAL_NETWORK"

    /** The Android release that introduced the permission (API level 37). */
    const val FIRST_SDK = 37

    /**
     * True for an address in the local network: RFC 1918 private IPv4, link-local (`169.254/16`,
     * `fe80::/10`), carrier-grade NAT (`100.64/10`, where Tailscale addresses live) and IPv6
     * unique local addresses (`fc00::/7`). Loopback, wildcard, multicast and public addresses are
     * not local. (Java hands an IPv4-mapped IPv6 address over as the IPv4 address inside it.)
     */
    fun isLocal(address: InetAddress): Boolean =
        !(address.isLoopbackAddress || address.isAnyLocalAddress || address.isMulticastAddress) &&
            RANGES.any { it.contains(address.address) }

    private val RANGES = listOf(
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "169.254.0.0/16",
        "100.64.0.0/10",
        "fc00::/7",
        "fe80::/10"
    ).map(::Cidr)

    private const val BITS_PER_BYTE = 8
    private const val BYTE_MASK = 0xFF

    /** A network `address/prefix`; an address of the other family never matches. */
    private class Cidr(text: String) {
        private val base: ByteArray
        private val prefix: Int

        init {
            val (host, bits) = text.split('/')
            base = InetAddress.getByName(host).address
            prefix = bits.toInt()
        }

        fun contains(address: ByteArray): Boolean {
            val whole = prefix / BITS_PER_BYTE
            val rest = prefix % BITS_PER_BYTE
            val mask = (BYTE_MASK shl (BITS_PER_BYTE - rest)) and BYTE_MASK
            return address.size == base.size &&
                (0 until whole).all { address[it] == base[it] } &&
                (rest == 0 || ((address[whole].toInt() xor base[whole].toInt()) and mask) == 0)
        }
    }
}

/** Resolves a host name to its addresses; replaceable in tests. */
fun interface HostResolver {
    suspend fun resolve(host: String): List<InetAddress>
}

/** The system resolver, off the main thread and bounded, so a slow DNS cannot stall the UI. */
class SystemHostResolver(
    private val dispatcher: CoroutineDispatcher = Dispatchers.IO,
    private val timeoutMs: Long = RESOLVE_TIMEOUT_MS
) : HostResolver {
    override suspend fun resolve(host: String): List<InetAddress> = withContext(dispatcher) {
        withTimeoutOrNull(timeoutMs) {
            try {
                InetAddress.getAllByName(host).toList()
            } catch (_: UnknownHostException) {
                emptyList()
            }
        } ?: emptyList()
    }

    private companion object {
        const val RESOLVE_TIMEOUT_MS = 4_000L
    }
}
