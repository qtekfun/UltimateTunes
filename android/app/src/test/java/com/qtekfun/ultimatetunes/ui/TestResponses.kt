// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui

import com.qtekfun.ultimatetunes.ui.model.LoadState
import kotlinx.coroutines.flow.Flow
import mockwebserver3.MockResponse
import mockwebserver3.SocketEffect
import okhttp3.Headers.Companion.headersOf

/*
 * Answers for FakeTunesServer overrides: what the contract examples do not cover (empty lists,
 * errors, dropped connections).
 */

/** A JSON answer. */
fun jsonResponse(body: String, code: Int = 200): MockResponse =
    MockResponse(code = code, headers = headersOf("Content-Type", "application/json"), body = body)

/** A successful OpenSubsonic envelope with [key] set to [value] (JSON). */
fun subsonicOk(key: String, value: String): MockResponse = jsonResponse(
    """{"subsonic-response":{"status":"ok","version":"1.16.1","type":"UltimateTunes",""" +
        """"serverVersion":"0.1.0","openSubsonic":true,"$key":$value}}"""
)

/** A failed OpenSubsonic envelope with error [code] (HTTP 200, as the server sends it). */
fun subsonicFailure(code: Int): MockResponse = jsonResponse(
    """{"subsonic-response":{"status":"failed","version":"1.16.1","type":"UltimateTunes",""" +
        """"serverVersion":"0.1.0","openSubsonic":true,"error":{"code":$code,"message":"x"}}}"""
)

/** A `/ut/v1` problem document with [code]. */
fun problem(status: Int, code: String): MockResponse = MockResponse(
    code = status,
    headers = headersOf("Content-Type", "application/problem+json"),
    body = """{"type":"about:blank","title":"Error","status":$status,"code":"$code"}"""
)

/** The connection drops before an answer: a network error for the client. */
fun dropConnection(): MockResponse =
    MockResponse.Builder().onResponseStart(SocketEffect.CloseSocket()).build()

/** The value of the first ready state of this flow. */
suspend fun <T> Flow<LoadState<T>>.awaitReady(): T =
    (awaitFirst { it is LoadState.Ready } as LoadState.Ready).value

/** The first state of this flow that is not loading. */
suspend fun <T> Flow<LoadState<T>>.awaitLoaded(): LoadState<T> =
    awaitFirst { it !is LoadState.Loading }
