// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.connect

import com.qtekfun.ultimatetunes.core.api.ErrorKind
import com.qtekfun.ultimatetunes.core.api.ServerConfig
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.model.ApiKeySecret
import okhttp3.HttpUrl

/** The outcome of [ConnectChecker.check]. */
sealed interface ConnectCheck {
    /** The server and key work, and [ConnectionGate] keeps them; [name] is the server's. */
    data class Connected(val name: String) : ConnectCheck

    data class Failed(val error: ConnectError) : ConnectCheck
}

/** The outcome of [ConnectChecker.signIn]. */
sealed interface SignInCheck {
    /** Signed in and connected, or why not. */
    data class Checked(val check: ConnectCheck) : SignInCheck

    /** The password is right, and the account also needs its two-factor code. */
    data object NeedsCode : SignInCheck
}

/** What the user typed to sign in. [toString] hides the password and the code. */
data class Credentials(val username: String, val password: String, val code: String? = null) {
    override fun toString(): String =
        "Credentials(username=$username, password=redacted, code=${code?.let { "redacted" }})"
}

/**
 * The server-side checks of a connection (SPEC §7, T12): `GET /ut/v1/server` first, which needs
 * no key and leaves the current connection alone, then `GET /ut/v1/me` with the key through
 * [ConnectionGate.tryConfig], which keeps the new server only if the key works and otherwise puts
 * the previous one back. Shared by the Connect screen and connect links.
 */
class ConnectChecker(private val api: TunesApi, private val gate: ConnectionGate) {
    suspend fun check(url: HttpUrl, key: ApiKeySecret): ConnectCheck =
        when (val info = api.serverInfo(url)) {
            is TunesResult.Success -> checkKey(url, key, info.value.name)
            is TunesResult.Failure -> serverFailure(info)
        }

    /**
     * Signs in with username and password (`POST /ut/v1/keys`), which gives this device a key
     * of its own named [deviceName], then checks that key as [check] does. The password and the
     * code go only to [url], and only once it answered as an UltimateTunes server.
     */
    suspend fun signIn(url: HttpUrl, credentials: Credentials, deviceName: String): SignInCheck {
        val serverName = when (val info = api.serverInfo(url)) {
            is TunesResult.Success -> info.value.name
            is TunesResult.Failure -> return SignInCheck.Checked(serverFailure(info))
        }
        val created = api.createKey(
            url,
            credentials.username,
            credentials.password,
            deviceName,
            credentials.code
        )
        val failure = when (created) {
            is TunesResult.Success ->
                return SignInCheck.Checked(checkKey(url, created.value.secret, serverName))

            is TunesResult.Unauthorized -> when {
                created.error.kind == ErrorKind.SECOND_FACTOR_REQUIRED -> return SignInCheck.NeedsCode
                created.error.kind == ErrorKind.ACCOUNT_DISABLED -> ConnectError.ACCOUNT_DISABLED
                credentials.code != null -> ConnectError.WRONG_CODE
                else -> ConnectError.WRONG_PASSWORD
            }

            is TunesResult.ApiError -> when (created.error.kind) {
                ErrorKind.RATE_LIMITED -> ConnectError.TOO_MANY_TRIES
                // The only 403 after a right password: the server wants 2FA set up first.
                ErrorKind.FORBIDDEN -> ConnectError.TWO_FACTOR_SETUP_REQUIRED
                else -> ConnectError.SERVER_ERROR
            }

            is TunesResult.NetworkError -> ConnectError.UNREACHABLE

            is TunesResult.Failure -> ConnectError.SERVER_ERROR
        }
        return SignInCheck.Checked(ConnectCheck.Failed(failure))
    }

    private fun serverFailure(failure: TunesResult.Failure): ConnectCheck.Failed =
        ConnectCheck.Failed(
            when (failure) {
                is TunesResult.NetworkError -> ConnectError.UNREACHABLE
                is TunesResult.ProtocolError -> ConnectError.NOT_A_SERVER
                else -> ConnectError.SERVER_ERROR
            }
        )

    private suspend fun checkKey(
        url: HttpUrl,
        key: ApiKeySecret,
        serverName: String
    ): ConnectCheck = when (gate.tryConfig(ServerConfig(url, key)) { api.me() }) {
        is TunesResult.Success -> ConnectCheck.Connected(serverName)
        is TunesResult.Unauthorized -> ConnectCheck.Failed(ConnectError.KEY_REFUSED)
        is TunesResult.NetworkError -> ConnectCheck.Failed(ConnectError.UNREACHABLE)
        is TunesResult.Failure -> ConnectCheck.Failed(ConnectError.SERVER_ERROR)
    }
}
