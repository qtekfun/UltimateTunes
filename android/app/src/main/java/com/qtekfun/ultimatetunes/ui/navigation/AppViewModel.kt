// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.navigation

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.ui.connect.ConnectionGate
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.stateIn

/**
 * Whether the app shows the Connect screen or the tabs, derived from the configured server: a
 * fresh process without one, or a key the server refused, always lands on Connect.
 */
@HiltViewModel
class AppViewModel @Inject constructor(private val gate: ConnectionGate) : ViewModel() {
    val showConnect: StateFlow<Boolean> =
        gate.needsConnect.stateIn(viewModelScope, SharingStarted.Eagerly, gate.needsConnectNow)

    /** Drops the refused or missing configuration and goes back to Connect. */
    fun reconnect() {
        gate.disconnect()
    }
}
