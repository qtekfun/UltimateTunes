// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.settings

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.core.api.ServerConfigSource
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.getOrNull
import com.qtekfun.ultimatetunes.core.api.model.ApiKey
import com.qtekfun.ultimatetunes.core.api.model.ApiKeyId
import com.qtekfun.ultimatetunes.core.api.model.Role
import com.qtekfun.ultimatetunes.ui.connect.ConnectionGate
import com.qtekfun.ultimatetunes.ui.model.LoadError
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.model.loadStateOf
import com.qtekfun.ultimatetunes.ui.model.toLoadError
import dagger.hilt.android.lifecycle.HiltViewModel
import java.time.Instant
import javax.inject.Inject
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** The server this device is connected to, and as whom. */
data class ServerDetails(
    val address: String,
    /** Null when `GET /ut/v1/server` did not answer. */
    val name: String?,
    val version: String?,
    val username: String,
    val isAdmin: Boolean
)

/** An API key of the user, as Settings lists it (never the key itself). */
data class KeyRow(
    val id: ApiKeyId,
    val name: String,
    val prefix: String,
    val createdAt: Instant,
    val lastUsedAt: Instant?,
    val revoked: Boolean,
    /** The key this device uses: it cannot be revoked from here. */
    val current: Boolean
) {
    val canRevoke: Boolean get() = !revoked && !current
}

/** What Settings shows. */
data class SettingsUiState(
    val server: LoadState<ServerDetails> = LoadState.Loading,
    val keys: LoadState<List<KeyRow>> = LoadState.Loading,
    val playback: PlaybackSettings = PlaybackSettings(),
    /** A revoke that failed, shown once. */
    val message: LoadError? = null
)

/**
 * Settings (RF-11): the server and account, the user's API keys per device (`/ut/v1/keys`, with
 * revoke), the playback cache size and offline choices ([PlaybackSettingsStore]), and Disconnect.
 */
@HiltViewModel
class SettingsViewModel @Inject constructor(
    private val api: TunesApi,
    private val configSource: ServerConfigSource,
    private val gate: ConnectionGate,
    private val store: PlaybackSettingsStore
) : ViewModel() {
    private val mutableState = MutableStateFlow(SettingsUiState())
    val state: StateFlow<SettingsUiState> = mutableState.asStateFlow()

    private var loading: Job? = null

    init {
        viewModelScope.launch {
            store.settings.collect { settings ->
                mutableState.update { it.copy(playback = settings) }
            }
        }
        load()
    }

    fun load() {
        if (loading?.isActive == true) return
        mutableState.update { it.copy(server = LoadState.Loading, keys = LoadState.Loading) }
        loading = viewModelScope.launch {
            val keys = async { loadKeys() }
            val server = loadServer()
            mutableState.update { it.copy(server = server, keys = keys.await()) }
        }
    }

    private suspend fun loadServer(): LoadState<ServerDetails> {
        val config = configSource.config.value
            ?: return LoadState.Failed(LoadError.NOT_CONFIGURED)
        return coroutineScope {
            val info = async { api.serverInfo(config.root) }
            val me = api.me()
            val server = info.await().getOrNull()
            loadStateOf(me) {
                ServerDetails(
                    address = config.root.toString(),
                    name = server?.name,
                    version = server?.version,
                    username = it.username,
                    isAdmin = it.role == Role.ADMIN
                )
            }
        }
    }

    private suspend fun loadKeys(): LoadState<List<KeyRow>> =
        loadStateOf(api.listKeys()) { list -> list.keys.map { it.toRow() } }

    /** Revokes another device's key (never this device's own). */
    fun revoke(id: ApiKeyId) {
        val keys = (mutableState.value.keys as? LoadState.Ready)?.value ?: return
        if (keys.none { it.id == id && it.canRevoke }) return
        viewModelScope.launch {
            when (val result = api.revokeKey(id)) {
                is TunesResult.Success -> {
                    val reloaded = loadKeys()
                    mutableState.update { it.copy(keys = reloaded) }
                }

                is TunesResult.Failure -> mutableState.update {
                    it.copy(message = result.toLoadError())
                }
            }
        }
    }

    fun dismissMessage() {
        mutableState.update { it.copy(message = null) }
    }

    fun setCacheSizeMb(value: Int) {
        viewModelScope.launch { store.setCacheSizeMb(value) }
    }

    fun setOfflineOnly(value: Boolean) {
        viewModelScope.launch { store.setOfflineOnly(value) }
    }

    fun setDownloadOnWifiOnly(value: Boolean) {
        viewModelScope.launch { store.setDownloadOnWifiOnly(value) }
    }

    /** Forgets the server and key on this device: back to the Connect screen. */
    fun disconnect() {
        gate.disconnect()
    }

    private fun ApiKey.toRow() = KeyRow(
        id = id,
        name = name,
        prefix = prefix,
        createdAt = createdAt,
        lastUsedAt = lastUsedAt,
        revoked = revokedAt != null,
        current = current
    )
}
