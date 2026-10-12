// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.api.internal

import com.qtekfun.ultimatetunes.core.api.ServerConfig
import com.qtekfun.ultimatetunes.core.api.ServerConfigSource
import okhttp3.HttpUrl
import okhttp3.Interceptor
import okhttp3.Response

/** Marks a request that must go out without the API key (`GET /ut/v1/server`, `POST /ut/v1/keys`). */
internal object NoAuth

/**
 * Adds the credentials of the current [ServerConfig] at send time, and only to requests for that
 * server (same scheme, host, port and path prefix), so the key never reaches another host:
 * - `/rest/…`: the OpenSubsonic parameters `apiKey`, `v`, `c` and `f=json` (the
 *   `apiKeyAuthentication` extension takes the key only as a parameter);
 * - `/ut/v1/…`: the `X-Api-Key` header.
 *
 * The URLs the rest of the app holds (stream, cover art) therefore never contain the key.
 * Install it as a **network** interceptor: it then sees every hop of a redirect, and a redirect to
 * another host goes out without the key (OkHttp only strips `Authorization` by itself).
 */
internal class AuthInterceptor(
    private val configSource: ServerConfigSource,
    private val clientName: String
) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val request = chain.request()
        val config = configSource.config.value
        if (config == null || request.tag(NoAuth::class.java) != null) {
            return chain.proceed(request)
        }
        val url = request.url
        return when {
            url.isUnder(config.root, REST_PREFIX) -> chain.proceed(
                request.newBuilder().url(url.withSubsonicParams(config)).build()
            )

            url.isUnder(config.root, UT_PREFIX) -> chain.proceed(
                request.newBuilder().header(API_KEY_HEADER, config.apiKey.value).build()
            )

            else -> chain.proceed(request)
        }
    }

    private fun HttpUrl.withSubsonicParams(config: ServerConfig): HttpUrl = newBuilder()
        .setQueryParameter(API_KEY_PARAM, config.apiKey.value)
        .setQueryParameter("v", SUBSONIC_VERSION)
        .setQueryParameter("c", clientName)
        .setQueryParameter("f", "json")
        .build()

    private fun HttpUrl.isUnder(root: HttpUrl, prefix: String): Boolean = scheme == root.scheme &&
        host == root.host &&
        port == root.port &&
        encodedPath.startsWith(root.encodedPath + prefix)

    companion object {
        const val API_KEY_HEADER = "X-Api-Key"
        const val API_KEY_PARAM = "apiKey"

        /** The OpenSubsonic protocol version the client speaks (the server's, contracts). */
        const val SUBSONIC_VERSION = "1.16.1"
        const val REST_PREFIX = "rest/"
        const val UT_PREFIX = "ut/v1/"
    }
}
