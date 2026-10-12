// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.connect

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
            is TunesResult.NetworkError -> ConnectCheck.Failed(ConnectError.UNREACHABLE)
            is TunesResult.ProtocolError -> ConnectCheck.Failed(ConnectError.NOT_A_SERVER)
            is TunesResult.Failure -> ConnectCheck.Failed(ConnectError.SERVER_ERROR)
        }

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
