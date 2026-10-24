// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.connect

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.core.api.ServerConfig
import com.qtekfun.ultimatetunes.core.api.TunesApi
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
    SERVER_ERROR,

    /** Wrong username or password (the server never says which). */
    WRONG_PASSWORD,

    /** The two-factor code (or recovery code) was not accepted. */
    WRONG_CODE,

    /** The account is disabled. */
    ACCOUNT_DISABLED,

    /** Too many failed tries from here or for this user: wait and try again. */
    TOO_MANY_TRIES,

    /** The server requires two-factor authentication, and this account has not set it up. */
    TWO_FACTOR_SETUP_REQUIRED
}

/** How the Connect screen signs in. */
enum class ConnectMethod {
    /** Username and password: the server creates a key for this device. */
    PASSWORD,

    /** An API key created in the admin panel or the web player. */
    API_KEY
}

/** What the Connect screen shows. */
data class ConnectUiState(
    val serverUrl: String = "",
    val method: ConnectMethod = ConnectMethod.PASSWORD,
    val username: String = "",
    val password: String = "",
    /** The server asked for the two-factor code: the screen shows [code]. */
    val needsCode: Boolean = false,
    val code: String = "",
    val apiKey: String = "",
    val checking: Boolean = false,
    val error: ConnectError? = null,
    /**
     * Set once the key works: the name the server reported. The root then shows the tabs; what
     * was typed is cleared at that moment, and everything on the next reconnect.
     */
    val connectedTo: String? = null
) {
    val canConnect: Boolean
        get() = !checking && serverUrl.isNotBlank() && when (method) {
            ConnectMethod.PASSWORD ->
                username.isNotBlank() && password.isNotEmpty() && (!needsCode || code.isNotBlank())

            ConnectMethod.API_KEY -> apiKey.isNotBlank()
        }

    /** Never shows the password, the code or the key, which may be typed in full. */
    override fun toString(): String =
        "ConnectUiState(serverUrl=$serverUrl, method=$method, username=$username, " +
            "password=redacted, needsCode=$needsCode, code=redacted, apiKey=redacted, " +
            "checking=$checking, error=$error, connectedTo=$connectedTo)"
}

/** The name a new key gets on the server, so the user can tell their devices apart. */
fun interface DeviceName {
    fun get(): String
}

/**
 * The Connect screen (RF-11): server URL with username and password (the server creates a key
 * for this device, `POST /ut/v1/keys`, asking for the two-factor code when the account has one)
 * or with an API key. Either key is checked against the server (`GET /ut/v1/server`, then `GET
 * /ut/v1/me`) before [gate] keeps it. Keeping it across restarts (Keystore-encrypted) is PLAN T17.
 */
@HiltViewModel
@Suppress("TooManyFunctions") // One handler per field of the form, and the two ways in.
class ConnectViewModel @Inject constructor(
    api: TunesApi,
    gate: ConnectionGate,
    private val cleartext: CleartextPolicy,
    demo: Optional<DemoServer> = Optional.empty(),
    private val deviceName: DeviceName = DeviceName { DEFAULT_DEVICE_NAME }
) : ViewModel() {
    private val checker = ConnectChecker(api, gate)
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
                    it.copy(
                        serverUrl = config.root.toString(),
                        method = ConnectMethod.API_KEY,
                        apiKey = config.apiKey.value
                    )
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

    fun onMethodChange(method: ConnectMethod) {
        mutableState.update { if (it.checking) it else it.copy(method = method, error = null) }
    }

    /** Another user forgets that the previous one needed a code. */
    fun onUsernameChange(value: String) {
        mutableState.update {
            it.copy(username = value, error = null, needsCode = false, code = "")
        }
    }

    fun onPasswordChange(value: String) {
        mutableState.update { it.copy(password = value, error = null) }
    }

    fun onCodeChange(value: String) {
        mutableState.update { it.copy(code = value, error = null) }
    }

    fun connect() {
        val current = mutableState.value
        if (!current.canConnect) return
        when (current.method) {
            ConnectMethod.API_KEY -> connectWithKey(current)
            ConnectMethod.PASSWORD -> signIn(current)
        }
    }

    private fun connectWithKey(current: ConnectUiState) {
        val validated = validate(current.serverUrl, current.apiKey)
        if (validated is Validated.Invalid) {
            mutableState.update { it.copy(error = validated.error) }
            return
        }
        mutableState.update { it.copy(checking = true, error = null) }
        viewModelScope.launch { finish(validated) }
    }

    private fun signIn(current: ConnectUiState) {
        val url = when (val checked = checkUrl(current.serverUrl)) {
            is UrlCheck.Valid -> checked.url

            is UrlCheck.Invalid -> {
                mutableState.update { it.copy(error = checked.error) }
                return
            }
        }
        val credentials = Credentials(
            username = current.username.trim(),
            password = current.password,
            code = current.code.trim().takeIf { current.needsCode && it.isNotEmpty() }
        )
        mutableState.update { it.copy(checking = true, error = null) }
        viewModelScope.launch {
            when (val result = checker.signIn(url, credentials, deviceName())) {
                SignInCheck.NeedsCode -> mutableState.update {
                    it.copy(checking = false, needsCode = true, code = "")
                }

                is SignInCheck.Checked -> settle(result.check)
            }
        }
    }

    /** The name of the new key: the phone's model, at most what the server accepts. */
    private fun deviceName(): String = deviceName.get()
        .filter { !it.isISOControl() }
        .trim()
        .take(MAX_DEVICE_NAME)
        .ifBlank { DEFAULT_DEVICE_NAME }

    private sealed interface Validated {
        data class Valid(val url: HttpUrl, val key: ApiKeySecret) : Validated

        data class Invalid(val error: ConnectError) : Validated
    }

    private sealed interface UrlCheck {
        data class Valid(val url: HttpUrl) : UrlCheck

        data class Invalid(val error: ConnectError) : UrlCheck
    }

    /** The local checks of the address, before anything is sent to it. */
    private fun checkUrl(serverUrl: String): UrlCheck {
        val url = normalizeServerUrl(serverUrl)
        return when {
            url == null -> UrlCheck.Invalid(ConnectError.INVALID_URL)

            !url.isHttps && !cleartext.isPermitted(url.host) ->
                UrlCheck.Invalid(ConnectError.INSECURE_URL)

            else -> UrlCheck.Valid(url)
        }
    }

    /** The local checks of the address and key, before asking the server. */
    private fun validate(serverUrl: String, apiKey: String): Validated {
        val key = apiKey.trim()
        return when (val url = checkUrl(serverUrl)) {
            is UrlCheck.Invalid -> Validated.Invalid(url.error)

            is UrlCheck.Valid -> if (ApiKeySecret.isWellFormed(key)) {
                Validated.Valid(url.url, ApiKeySecret(key))
            } else {
                Validated.Invalid(ConnectError.INVALID_KEY)
            }
        }
    }

    /** Asks the server (when [validated] is valid) and ends the check. */
    private suspend fun finish(validated: Validated) {
        settle(
            when (validated) {
                is Validated.Invalid -> ConnectCheck.Failed(validated.error)
                is Validated.Valid -> checker.check(validated.url, validated.key)
            }
        )
    }

    private fun settle(result: ConnectCheck) {
        mutableState.update {
            when (result) {
                // The key is kept by the gate; the form forgets what was typed.
                is ConnectCheck.Connected -> ConnectUiState(connectedTo = result.name)

                is ConnectCheck.Failed -> it.copy(checking = false, error = result.error)
            }
        }
    }

    companion object {
        /** The name of a key when the phone reports no model. */
        const val DEFAULT_DEVICE_NAME = "Android"

        /** The longest key name the server accepts (`POST /ut/v1/keys`). */
        const val MAX_DEVICE_NAME = 100

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
