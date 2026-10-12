// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.connect

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.core.api.InMemoryServerConfigSource
import com.qtekfun.ultimatetunes.core.api.ServerConfig
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.model.ApiKeySecret
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull

/** Why connecting failed, as the Connect screen explains it. */
enum class ConnectError {
    /** The address is not a URL. */
    INVALID_URL,

    /** The key does not have the shape of an UltimateTunes key (`utk_…`). */
    INVALID_KEY,

    /** Nothing answered at the address. */
    UNREACHABLE,

    /** Something answered, but it is not an UltimateTunes server. */
    NOT_A_SERVER,

    /** The server refused the key (unknown, revoked or disabled account). */
    KEY_REFUSED,

    /** The server answered with an error. */
    SERVER_ERROR
}

/** What the Connect screen shows. */
data class ConnectUiState(
    val serverUrl: String = "",
    val apiKey: String = "",
    val checking: Boolean = false,
    val error: ConnectError? = null,
    /** Set once the key works: the name the server reported. The screen then moves on. */
    val connectedTo: String? = null
) {
    val canConnect: Boolean get() = !checking && serverUrl.isNotBlank() && apiKey.isNotBlank()
}

/**
 * The Connect screen (RF-11): server URL and API key, checked against the server (`GET
 * /ut/v1/server`, then `GET /ut/v1/me` with the key) before they are kept in [configSource].
 * Keeping them across restarts (Keystore-encrypted) is PLAN T17.
 */
@HiltViewModel
class ConnectViewModel @Inject constructor(
    private val api: TunesApi,
    private val configSource: InMemoryServerConfigSource
) : ViewModel() {
    private val mutableState = MutableStateFlow(ConnectUiState())
    val state: StateFlow<ConnectUiState> = mutableState.asStateFlow()

    fun onServerUrlChange(value: String) {
        mutableState.update { it.copy(serverUrl = value, error = null) }
    }

    fun onApiKeyChange(value: String) {
        mutableState.update { it.copy(apiKey = value, error = null) }
    }

    fun connect() {
        val current = mutableState.value
        if (current.checking) return
        val url = normalizeServerUrl(current.serverUrl)
        val key = current.apiKey.trim()
        val invalid = when {
            url == null -> ConnectError.INVALID_URL
            !ApiKeySecret.isWellFormed(key) -> ConnectError.INVALID_KEY
            else -> null
        }
        if (invalid != null || url == null) {
            mutableState.update { it.copy(error = invalid) }
            return
        }
        mutableState.update { it.copy(checking = true, error = null) }
        viewModelScope.launch {
            val result = check(url, ApiKeySecret(key))
            mutableState.update {
                when (result) {
                    is CheckResult.Connected -> it.copy(checking = false, connectedTo = result.name)
                    is CheckResult.Failed -> it.copy(checking = false, error = result.error)
                }
            }
        }
    }

    private sealed interface CheckResult {
        data class Connected(val name: String) : CheckResult

        data class Failed(val error: ConnectError) : CheckResult
    }

    /** Checks the address, then the key (kept in [configSource] only if it works). */
    private suspend fun check(url: HttpUrl, key: ApiKeySecret): CheckResult =
        when (val info = api.serverInfo(url)) {
            is TunesResult.Success -> checkKey(url, key, info.value.name)
            is TunesResult.NetworkError -> CheckResult.Failed(ConnectError.UNREACHABLE)
            is TunesResult.ProtocolError -> CheckResult.Failed(ConnectError.NOT_A_SERVER)
            is TunesResult.Failure -> CheckResult.Failed(ConnectError.SERVER_ERROR)
        }

    private suspend fun checkKey(url: HttpUrl, key: ApiKeySecret, serverName: String): CheckResult {
        val previous = configSource.config.value
        configSource.set(ServerConfig(url, key))
        val me = api.me()
        if (me is TunesResult.Success) return CheckResult.Connected(serverName)
        configSource.set(previous)
        return CheckResult.Failed(
            when (me) {
                is TunesResult.Unauthorized -> ConnectError.KEY_REFUSED
                is TunesResult.NetworkError -> ConnectError.UNREACHABLE
                else -> ConnectError.SERVER_ERROR
            }
        )
    }

    companion object {
        /**
         * The server root for what the user typed: trimmed, `https://` when no scheme is given,
         * only `http`/`https`, without query or fragment and with a trailing slash. Null when it
         * is not a URL.
         */
        fun normalizeServerUrl(input: String): HttpUrl? {
            val trimmed = input.trim()
            val withScheme = if ("://" in trimmed) trimmed else "https://$trimmed"
            return withScheme
                .takeIf { trimmed.isNotEmpty() && trimmed.none { it.isWhitespace() } }
                ?.toHttpUrlOrNull()
                ?.let(ServerConfig::rootOf)
        }
    }
}
