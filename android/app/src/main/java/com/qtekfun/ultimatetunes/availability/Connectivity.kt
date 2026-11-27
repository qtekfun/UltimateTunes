// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.availability

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Whether the phone has a network at all. A server on the LAN or a VPN needs no Internet, so the
 * network is not asked to be validated; a server that does not answer shows as failed requests.
 */
interface Connectivity {
    val online: StateFlow<Boolean>
}

/** [Connectivity] from Android's default network. */
@Singleton
class DeviceConnectivity @Inject constructor(@ApplicationContext context: Context) :
    Connectivity {
    private val manager = context.getSystemService(ConnectivityManager::class.java)
    private val state = MutableStateFlow(manager.activeNetwork != null)

    override val online: StateFlow<Boolean> = state.asStateFlow()

    init {
        manager.registerDefaultNetworkCallback(object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                state.value = true
            }

            override fun onLost(network: Network) {
                state.value = false
            }
        })
    }
}
