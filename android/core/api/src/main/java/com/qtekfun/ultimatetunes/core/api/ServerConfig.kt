// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.api

import com.qtekfun.ultimatetunes.core.api.model.ApiKeySecret
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import okhttp3.HttpUrl

/**
 * The server the app talks to: its base URL (e.g. `https://music.example.net/`, possibly with a
 * path prefix) and the device's API key. [toString] never shows the key.
 */
data class ServerConfig(val baseUrl: HttpUrl, val apiKey: ApiKeySecret) {
    /** [baseUrl] without query and with a trailing slash, so endpoint paths resolve under it. */
    val root: HttpUrl = rootOf(baseUrl)

    override fun toString(): String = "ServerConfig(baseUrl=$root, apiKey=$apiKey)"

    companion object {
        /** [url] without query or fragment and with a trailing slash. */
        fun rootOf(url: HttpUrl): HttpUrl {
            val clean = url.newBuilder().query(null).fragment(null).build()
            return if (clean.encodedPath.endsWith(
                    "/"
                )
            ) {
                clean
            } else {
                clean.newBuilder().addPathSegment("").build()
            }
        }
    }
}

/**
 * Where [TunesApi] reads the current [ServerConfig] on every call, so a new key or URL takes
 * effect at once. The default implementation keeps it in memory; persistence (the key encrypted
 * with the Android Keystore) is the app's job (PLAN T17), which can bind its own implementation.
 */
interface ServerConfigSource {
    val config: StateFlow<ServerConfig?>
}

/** A [ServerConfigSource] whose value is set by the app (Connect screen, settings, tests). */
class InMemoryServerConfigSource(initial: ServerConfig? = null) : ServerConfigSource {
    private val state = MutableStateFlow(initial)

    override val config: StateFlow<ServerConfig?> = state.asStateFlow()

    fun set(config: ServerConfig?) {
        state.value = config
    }
}
