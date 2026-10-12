// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.connect

import com.qtekfun.ultimatetunes.core.api.InMemoryServerConfigSource
import com.qtekfun.ultimatetunes.core.api.ServerConfig
import com.qtekfun.ultimatetunes.core.api.TunesResult
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.flow.filter
import kotlinx.coroutines.flow.map

/**
 * Whether the app is connected, derived from the configured server (never from a restored back
 * stack): no configuration, a key under test or a refused key all mean the Connect screen.
 */
@Singleton
class ConnectionGate @Inject constructor(private val configSource: InMemoryServerConfigSource) {
    private val checking = MutableStateFlow(false)

    /** True while the Connect screen must show. */
    val needsConnect: Flow<Boolean> =
        combine(configSource.config, checking) { config, checking -> config == null || checking }

    /**
     * Emits each time the app goes back to the Connect screen after a collector started (a refused
     * key, "Connect Again", "Disconnect"), so activity-scoped state such as the player's queue and
     * the Connect form can start over.
     */
    val reconnects: Flow<Unit> =
        needsConnect.distinctUntilChanged().drop(1).filter { it }.map { }

    /** The current value of [needsConnect]. */
    val needsConnectNow: Boolean get() = configSource.config.value == null || checking.value

    /**
     * Makes [config] current while [check] runs (the API reads it from there) and keeps it only
     * if [check] succeeds; otherwise, or if cancelled, the previous configuration comes back.
     */
    suspend fun <T> tryConfig(
        config: ServerConfig,
        check: suspend () -> TunesResult<T>
    ): TunesResult<T> {
        val previous = configSource.config.value
        var kept = false
        checking.value = true
        try {
            configSource.set(config)
            val result = check()
            kept = result is TunesResult.Success
            return result
        } finally {
            if (!kept) configSource.set(previous)
            checking.value = false
        }
    }

    /** Forgets the server and key: the app goes back to the Connect screen. */
    fun disconnect() {
        configSource.set(null)
    }
}
