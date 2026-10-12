// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.api

import java.io.IOException
import java.time.Duration

/**
 * The outcome of every [TunesApi] call. IO never throws into the UI: each failure is one of the
 * [Failure] cases, which a view model can turn into a message or a navigation (for example
 * [Unauthorized] back to the Connect screen).
 */
sealed interface TunesResult<out T> {
    /** The call worked. */
    data class Success<out T>(val value: T) : TunesResult<T>

    /** Every way a call can fail. */
    sealed interface Failure : TunesResult<Nothing>

    /**
     * The server answered with an error that is not about credentials: an OpenSubsonic error
     * envelope or a `/ut/v1` problem, mapped to [error]. [httpStatus] is the HTTP status (200 for
     * most OpenSubsonic errors, contracts/errors.md).
     */
    data class ApiError(val error: TunesError, val httpStatus: Int) : Failure

    /**
     * The credentials were refused: missing, wrong, unknown or revoked key, token auth, conflicting
     * mechanisms or a disabled account. The app should ask for a new key.
     */
    data class Unauthorized(val error: TunesError, val httpStatus: Int) : Failure

    /** No answer: no connection, DNS, TLS or timeout. Retrying may work. */
    data class NetworkError(val cause: IOException) : Failure {
        override fun toString(): String = "NetworkError(${cause.javaClass.simpleName})"
    }

    /** An answer the client cannot understand (unexpected status, content or JSON). */
    data class ProtocolError(val reason: String, val httpStatus: Int) : Failure

    /** No server is configured yet (no URL and key): show the Connect screen. */
    data object NotConfigured : Failure
}

/** The value of a [TunesResult.Success], or null. */
fun <T> TunesResult<T>.getOrNull(): T? = (this as? TunesResult.Success)?.value

/** Transforms the value of a success and keeps any failure as it is. */
inline fun <T, R> TunesResult<T>.map(transform: (T) -> R): TunesResult<R> = when (this) {
    is TunesResult.Success -> TunesResult.Success(transform(value))
    is TunesResult.Failure -> this
}

/** Runs [action] on the value of a success. */
inline fun <T> TunesResult<T>.onSuccess(action: (T) -> Unit): TunesResult<T> {
    if (this is TunesResult.Success) action(value)
    return this
}

/** Runs [action] on a failure. */
inline fun <T> TunesResult<T>.onFailure(action: (TunesResult.Failure) -> Unit): TunesResult<T> {
    if (this is TunesResult.Failure) action(this)
    return this
}

/**
 * A server-side error, from an OpenSubsonic `error.code` or a `/ut/v1` problem `code`
 * (contracts/errors.md).
 *
 * @property kind what went wrong; switch on this, never on [message].
 * @property message the server's human-readable text (may change, may be null).
 * @property code the raw code: the OpenSubsonic number as text, or the problem `code`.
 * @property retryAfter how long to wait, for [ErrorKind.RATE_LIMITED].
 * @property helpUrl where the user can read more (e.g. how to create an API key).
 */
data class TunesError(
    val kind: ErrorKind,
    val message: String? = null,
    val code: String? = null,
    val retryAfter: Duration? = null,
    val helpUrl: String? = null
)

/** The `TunesError` classes of contracts/errors.md, as the client sees them. */
enum class ErrorKind(val isAuthentication: Boolean = false) {
    MISSING_PARAMETER,
    INVALID_PARAMETER,
    INVALID_ID,
    CLIENT_TOO_OLD,
    SERVER_TOO_OLD,
    AUTHENTICATION_REQUIRED(isAuthentication = true),
    AUTHENTICATION_FAILED(isAuthentication = true),
    TOKEN_AUTH_NOT_SUPPORTED(isAuthentication = true),
    CONFLICTING_AUTH(isAuthentication = true),
    INVALID_API_KEY(isAuthentication = true),
    ACCOUNT_DISABLED(isAuthentication = true),

    /** Authenticated but not allowed. OpenSubsonic code 50 also covers a disabled account. */
    FORBIDDEN,
    NOT_FOUND,
    CONFLICT,
    FEATURE_DISABLED,
    UNSUPPORTED_URL,
    PAYLOAD_TOO_LARGE,
    RATE_LIMITED,
    UPSTREAM_UNAVAILABLE,
    DOWNLOAD_FAILED,
    NOT_IMPLEMENTED,
    INTERNAL,

    /** OpenSubsonic code 0 without a more specific HTTP status. */
    GENERIC,

    /** A code this client does not know (a newer server). */
    UNKNOWN
}
