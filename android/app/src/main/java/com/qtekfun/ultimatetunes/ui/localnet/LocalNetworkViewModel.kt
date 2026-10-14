// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.localnet

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.core.api.InMemoryServerConfigSource
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** Whether the system lets this app talk to the local network (always true before Android 17). */
fun interface LocalNetworkPermission {
    fun isGranted(): Boolean
}

/** What the screens must show about the local network permission. */
data class LocalNetworkState(
    /** The server is on the local network and the system blocks it: connections time out. */
    val blocked: Boolean = false,
    /** The dialog that explains and asks is open. */
    val showDialog: Boolean = false,
    /** The user already answered the system prompt with "don't allow": only Settings can fix it. */
    val denied: Boolean = false
)

/**
 * Android 17 blocks connections to the local network unless the app holds `ACCESS_LOCAL_NETWORK`.
 * A server reached by a name that your DNS maps to `192.168.x.x` (split DNS) is one, and without
 * the permission every request just times out. This works out, from the configured server and
 * the permission, whether that is happening, so the app can ask, and later explain, instead of
 * spinning forever. It never contacts anything but the system resolver.
 */
@HiltViewModel
class LocalNetworkViewModel @Inject constructor(
    private val configSource: InMemoryServerConfigSource,
    private val permission: LocalNetworkPermission,
    private val resolver: HostResolver
) : ViewModel() {
    private val mutable = MutableStateFlow(LocalNetworkState())
    val state: StateFlow<LocalNetworkState> = mutable.asStateFlow()

    /** Looks again (the screen was shown, came back from Settings, or the server changed). */
    fun refresh() {
        val host = configSource.config.value?.baseUrl?.host
        if (host == null || permission.isGranted()) {
            mutable.value = LocalNetworkState()
            return
        }
        viewModelScope.launch {
            val local = isLocalHost(host)
            mutable.update { previous ->
                when {
                    !local -> LocalNetworkState()

                    // Newly blocked: explain at once; an earlier "not now" stays dismissed.
                    !previous.blocked -> LocalNetworkState(blocked = true, showDialog = true)

                    else -> previous
                }
            }
        }
    }

    /** The user answered the system prompt: granted closes everything, denied leads to Settings. */
    fun onPermissionResult(granted: Boolean) {
        mutable.value = if (granted) {
            LocalNetworkState()
        } else {
            LocalNetworkState(blocked = true, showDialog = true, denied = true)
        }
    }

    /** "Not now": the explanation closes; the network error screens keep a way back to it. */
    fun dismiss() {
        mutable.update { it.copy(showDialog = false) }
    }

    /** The error screens' "Allow" button, or any other way to open the explanation again. */
    fun reopen() {
        mutable.update { if (it.blocked) it.copy(showDialog = true) else it }
    }

    private suspend fun isLocalHost(host: String): Boolean {
        if (host.endsWith(".local", ignoreCase = true)) return true
        return resolver.resolve(host).any(LocalNetwork::isLocal)
    }
}
