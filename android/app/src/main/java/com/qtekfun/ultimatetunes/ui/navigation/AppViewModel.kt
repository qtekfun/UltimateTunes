// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.navigation

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.ui.connect.ConnectionGate
import com.qtekfun.ultimatetunes.ui.settings.AppPrefsStore
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
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
    private val prefs: AppPrefsStore
) : ViewModel() {
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
