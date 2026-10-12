// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.api.internal

import java.io.IOException
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlinx.coroutines.suspendCancellableCoroutine
import okhttp3.Call
import okhttp3.Callback
import okhttp3.Response

/** Status, headers and body of an HTTP answer, read in full (API responses are small). */
internal class HttpAnswer(
    val code: Int,
    val body: String,
    val contentType: String?,
    val retryAfter: String?
) {
    val isSuccessful: Boolean get() = code in SUCCESS

    private companion object {
        val SUCCESS = 200..299
    }
}

/**
 * Runs the call on OkHttp's own threads and reads the whole answer. Cancelling the coroutine
 * cancels the call.
 *
 * @throws IOException on network failure.
 */
internal suspend fun Call.await(): HttpAnswer = suspendCancellableCoroutine { continuation ->
    continuation.invokeOnCancellation { cancel() }
    enqueue(
        object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                continuation.resumeWithException(e)
            }

            override fun onResponse(call: Call, response: Response) {
                val answer = try {
                    response.use {
                        HttpAnswer(
                            code = it.code,
                            body = it.body.string(),
                            contentType = it.header("Content-Type"),
                            retryAfter = it.header("Retry-After")
                        )
                    }
                } catch (e: IOException) {
                    continuation.resumeWithException(e)
                    return
                }
                continuation.resume(answer)
            }
        }
    )
}
