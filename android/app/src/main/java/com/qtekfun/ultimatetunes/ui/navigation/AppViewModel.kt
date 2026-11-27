// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.navigation

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.availability.Connectivity
import com.qtekfun.ultimatetunes.core.api.ServerConfigSource
import com.qtekfun.ultimatetunes.core.library.CatalogSync
import com.qtekfun.ultimatetunes.playback.OfflineControls
import com.qtekfun.ultimatetunes.ui.connect.ConnectionGate
import com.qtekfun.ultimatetunes.ui.settings.AppPrefsStore
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.flow.filter
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

/**
 * Whether the app shows the Connect screen or the tabs, derived from the configured server: a
 * fresh process without one, or a key the server refused, always lands on Connect. Also whether
 * the notification permission still has to be explained (Android 13+, RF-13), once.
 */
@HiltViewModel
class AppViewModel @Inject constructor(
    private val gate: ConnectionGate,
    private val prefs: AppPrefsStore,
    private val offline: OfflineControls,
    private val catalog: CatalogSync,
    connectivity: Connectivity,
    configSource: ServerConfigSource
) : ViewModel() {
    init {
        // Once connected (the saved server is restored a moment after the start): drop what
        // another server left, and go on with a sync the process death stopped.
        viewModelScope.launch {
            combine(gate.needsConnect, configSource.config) { needsConnect, config ->
                config?.root?.toString().takeUnless { needsConnect }
            }
                .distinctUntilChanged()
                .filterNotNull()
                .collect { offline.serverConnected(it) }
        }
        // The local catalog follows the server at app start and on connect (a new address or key
        // too). A change of connection cancels the sync under way, which stores nothing.
        viewModelScope.launch {
            combine(gate.needsConnect, configSource.config) { needsConnect, config ->
                config.takeUnless { needsConnect }
            }
                .distinctUntilChanged()
                .collectLatest { if (it != null) catalog.syncIfStale() }
        }
        viewModelScope.launch { forgetCatalogOnDisconnect(configSource) }
        // Back online: what could not be read meanwhile (or never was) is read now.
        viewModelScope.launch {
            connectivity.online.drop(1).filter { it }.collect {
                if (!gate.needsConnectNow) catalog.syncIfStale()
            }
        }
    }

    /**
     * Clears the catalog when a connection is dropped: not while the saved one is not restored
     * yet, nor when a first attempt to connect fails.
     */
    private suspend fun forgetCatalogOnDisconnect(configSource: ServerConfigSource) {
        var connected = false
        combine(gate.needsConnect, configSource.config) { needsConnect, config ->
            needsConnect to config
        }.collect { (needsConnect, config) ->
            if (config == null) {
                if (connected) catalog.clear()
                connected = false
            } else if (!needsConnect) {
                connected = true
            }
        }
    }

    val showConnect: StateFlow<Boolean> =
        gate.needsConnect.stateIn(viewModelScope, SharingStarted.Eagerly, gate.needsConnectNow)

    /** True until the user answered the notification question once. */
    val askNotifications: StateFlow<Boolean> = prefs.notificationsAsked
        .map { !it }
        .stateIn(viewModelScope, SharingStarted.Eagerly, false)

    /** Drops the refused or missing configuration and goes back to Connect. */
    fun reconnect() {
        gate.disconnect()
    }

    /** The notification question was answered (either way): never ask again from the app. */
    fun onNotificationsAsked() {
        viewModelScope.launch { prefs.setNotificationsAsked(true) }
    }
}
