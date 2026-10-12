// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.connect

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.core.api.ServerConfig
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.model.ApiKeySecret
import dagger.hilt.android.lifecycle.HiltViewModel
import java.util.Optional
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

    /** A plain `http://` address, which this build refuses: use `https://`. */
    INSECURE_URL,

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
    /**
     * Set once the key works: the name the server reported. The root then shows the tabs; the
     * typed address and key are cleared at that moment, and everything on the next reconnect.
     */
    val connectedTo: String? = null
) {
    val canConnect: Boolean get() = !checking && serverUrl.isNotBlank() && apiKey.isNotBlank()

    /** Never shows the key, which may be typed in full. */
    override fun toString(): String =
        "ConnectUiState(serverUrl=$serverUrl, apiKey=redacted, checking=$checking, " +
            "error=$error, connectedTo=$connectedTo)"
}

/**
 * The Connect screen (RF-11): server URL and API key, checked against the server (`GET
 * /ut/v1/server`, then `GET /ut/v1/me` with the key) before [gate] keeps them. Keeping them
 * across restarts (Keystore-encrypted) is PLAN T17.
 */
@HiltViewModel
class ConnectViewModel @Inject constructor(
    private val api: TunesApi,
    private val gate: ConnectionGate,
    private val cleartext: CleartextPolicy,
    demo: Optional<DemoServer> = Optional.empty()
) : ViewModel() {
    private val mutableState = MutableStateFlow(ConnectUiState())
    val state: StateFlow<ConnectUiState> = mutableState.asStateFlow()

    init {
        // This view model lives as long as the activity: start over on every return to Connect.
        viewModelScope.launch { gate.reconnects.collect { mutableState.value = ConnectUiState() } }
    }

    private val demoServer: DemoServer? = demo.orElse(null)

    /** The label of the demo button, or null when this build has no demo (release builds). */
    val demoLabelRes: Int? = demoServer?.labelRes

    /** Starts the debug-only demo server and connects to it through the same checks. */
    fun tryDemo() {
        val demo = demoServer ?: return
        if (mutableState.value.checking) return
        mutableState.update { it.copy(checking = true, error = null) }
        viewModelScope.launch {
            val config = demo.start()
            if (config == null) {
                mutableState.update { it.copy(checking = false, error = ConnectError.UNREACHABLE) }
            } else {
                mutableState.update {
                    it.copy(serverUrl = config.root.toString(), apiKey = config.apiKey.value)
                }
                finish(validate(config.root.toString(), config.apiKey.value))
            }
        }
    }

    fun onServerUrlChange(value: String) {
        mutableState.update { it.copy(serverUrl = value, error = null) }
    }

    fun onApiKeyChange(value: String) {
        mutableState.update { it.copy(apiKey = value, error = null) }
    }

    fun connect() {
        val current = mutableState.value
        if (current.checking) return
        val validated = validate(current.serverUrl, current.apiKey)
        if (validated is Validated.Invalid) {
            mutableState.update { it.copy(error = validated.error) }
            return
        }
        mutableState.update { it.copy(checking = true, error = null) }
        viewModelScope.launch { finish(validated) }
    }

    private sealed interface Validated {
        data class Valid(val url: HttpUrl, val key: ApiKeySecret) : Validated

        data class Invalid(val error: ConnectError) : Validated
    }

    /** The local checks of the address and key, before asking the server. */
    private fun validate(serverUrl: String, apiKey: String): Validated {
        val url = normalizeServerUrl(serverUrl)
        val key = apiKey.trim()
        return when {
            url == null -> Validated.Invalid(ConnectError.INVALID_URL)

            !url.isHttps && !cleartext.isPermitted(url.host) ->
                Validated.Invalid(ConnectError.INSECURE_URL)

            !ApiKeySecret.isWellFormed(key) -> Validated.Invalid(ConnectError.INVALID_KEY)

            else -> Validated.Valid(url, ApiKeySecret(key))
        }
    }

    /** Asks the server (when [validated] is valid) and ends the check. */
    private suspend fun finish(validated: Validated) {
        val result = when (validated) {
            is Validated.Invalid -> CheckResult.Failed(validated.error)
            is Validated.Valid -> check(validated.url, validated.key)
        }
        mutableState.update {
            when (result) {
                // The key is kept by the gate; the form forgets what was typed.
                is CheckResult.Connected -> ConnectUiState(connectedTo = result.name)

                is CheckResult.Failed -> it.copy(checking = false, error = result.error)
            }
        }
    }

    private sealed interface CheckResult {
        data class Connected(val name: String) : CheckResult

        data class Failed(val error: ConnectError) : CheckResult
    }

    /** Checks the address, then the key (kept by [gate] only if it works). */
    private suspend fun check(url: HttpUrl, key: ApiKeySecret): CheckResult =
        when (val info = api.serverInfo(url)) {
            is TunesResult.Success -> checkKey(url, key, info.value.name)
            is TunesResult.NetworkError -> CheckResult.Failed(ConnectError.UNREACHABLE)
            is TunesResult.ProtocolError -> CheckResult.Failed(ConnectError.NOT_A_SERVER)
            is TunesResult.Failure -> CheckResult.Failed(ConnectError.SERVER_ERROR)
        }

    private suspend fun checkKey(url: HttpUrl, key: ApiKeySecret, serverName: String): CheckResult =
        when (gate.tryConfig(ServerConfig(url, key)) { api.me() }) {
            is TunesResult.Success -> CheckResult.Connected(serverName)
            is TunesResult.Unauthorized -> CheckResult.Failed(ConnectError.KEY_REFUSED)
            is TunesResult.NetworkError -> CheckResult.Failed(ConnectError.UNREACHABLE)
            is TunesResult.Failure -> CheckResult.Failed(ConnectError.SERVER_ERROR)
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
