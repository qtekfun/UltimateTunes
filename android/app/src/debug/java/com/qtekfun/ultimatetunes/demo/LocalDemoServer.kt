// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.demo

import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.core.api.ServerConfig
import com.qtekfun.ultimatetunes.core.api.model.ApiKeySecret
import com.qtekfun.ultimatetunes.ui.connect.DemoServer
import java.io.IOException
import java.net.InetAddress
import java.security.SecureRandom
import java.time.Clock
import java.util.Base64
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import mockwebserver3.MockWebServer
import okhttp3.HttpUrl

/**
 * The debug-only demo (see `ui.connect.DemoServer`): a MockWebServer bound to 127.0.0.1 inside
 * the app, answering with [DemoDispatcher]. The app reaches it through the normal `TunesApi` and
 * OkHttp stack, so the demo exercises the same code as a real server. The debug network security
 * config allows cleartext to 127.0.0.1 only; release builds contain none of this.
 */
@Singleton
class LocalDemoServer @Inject constructor(private val clock: Clock) : DemoServer {
    override val labelRes: Int = R.string.demo_try

    private val mutex = Mutex()
    private var running: ServerConfig? = null

    override suspend fun start(): ServerConfig? = mutex.withLock {
        running ?: withContext(Dispatchers.IO) {
            try {
                val key = randomKey()
                val server = MockWebServer()
                server.dispatcher = DemoDispatcher(key, clock)
                server.start(InetAddress.getByName(LOOPBACK), 0)
                val url = HttpUrl.Builder().scheme("http").host(LOOPBACK).port(server.port).build()
                ServerConfig(url, ApiKeySecret(key))
            } catch (e: IOException) {
                android.util.Log.w(TAG, "The demo server did not start", e)
                null
            }
        }.also { running = it }
    }

    private companion object {
        const val TAG = "UltimateTunesDemo"
        const val LOOPBACK = "127.0.0.1"
        const val KEY_BYTES = 32

        /** A fresh key per run, shaped like a real one (`utk_` + 43 base64url characters). */
        fun randomKey(): String {
            val bytes = ByteArray(KEY_BYTES).also { SecureRandom().nextBytes(it) }
            return "utk_" + Base64.getUrlEncoder().withoutPadding().encodeToString(bytes)
        }
    }
}
