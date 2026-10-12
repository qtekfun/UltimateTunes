// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.api.internal

import com.qtekfun.ultimatetunes.core.api.ErrorKind
import com.qtekfun.ultimatetunes.core.api.TunesError
import com.qtekfun.ultimatetunes.core.api.TunesResult
import java.time.Clock
import java.time.Duration
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import java.time.format.DateTimeParseException

/**
 * The client side of the mapping table in contracts/errors.md: OpenSubsonic error codes and
 * `/ut/v1` problem codes to [ErrorKind], in one place.
 */
internal object ErrorMapping {
    const val HTTP_UNAUTHORIZED = 401
    const val HTTP_TOO_MANY_REQUESTS = 429
    const val HTTP_NOT_IMPLEMENTED = 501

    @Suppress("MagicNumber") // The numeric codes are the contract (contracts/errors.md).
    private val subsonicCodes = mapOf(
        10 to ErrorKind.MISSING_PARAMETER,
        20 to ErrorKind.CLIENT_TOO_OLD,
        30 to ErrorKind.SERVER_TOO_OLD,
        40 to ErrorKind.AUTHENTICATION_FAILED,
        // 41 is reserved by the contract (token auth not supported), 42 is what the server sends.
        41 to ErrorKind.TOKEN_AUTH_NOT_SUPPORTED,
        42 to ErrorKind.TOKEN_AUTH_NOT_SUPPORTED,
        43 to ErrorKind.CONFLICTING_AUTH,
        44 to ErrorKind.INVALID_API_KEY,
        50 to ErrorKind.FORBIDDEN,
        70 to ErrorKind.NOT_FOUND
    )

    private val problemCodes = mapOf(
        "missing_parameter" to ErrorKind.MISSING_PARAMETER,
        "invalid_parameter" to ErrorKind.INVALID_PARAMETER,
        "invalid_id" to ErrorKind.INVALID_ID,
        "authentication_required" to ErrorKind.AUTHENTICATION_REQUIRED,
        "authentication_failed" to ErrorKind.AUTHENTICATION_FAILED,
        "conflicting_auth" to ErrorKind.CONFLICTING_AUTH,
        "invalid_api_key" to ErrorKind.INVALID_API_KEY,
        "account_disabled" to ErrorKind.ACCOUNT_DISABLED,
        "forbidden" to ErrorKind.FORBIDDEN,
        "not_found" to ErrorKind.NOT_FOUND,
        "conflict" to ErrorKind.CONFLICT,
        "feature_disabled" to ErrorKind.FEATURE_DISABLED,
        "unsupported_url" to ErrorKind.UNSUPPORTED_URL,
        "payload_too_large" to ErrorKind.PAYLOAD_TOO_LARGE,
        "rate_limited" to ErrorKind.RATE_LIMITED,
        "upstream_unavailable" to ErrorKind.UPSTREAM_UNAVAILABLE,
        "download_failed" to ErrorKind.DOWNLOAD_FAILED,
        "not_implemented" to ErrorKind.NOT_IMPLEMENTED,
        "internal_error" to ErrorKind.INTERNAL
    )

    /**
     * The kind of an OpenSubsonic `error.code`. Code 0 is generic; its HTTP status tells rate
     * limiting (429) and router stubs (501) apart.
     */
    fun subsonicKind(code: Int, httpStatus: Int): ErrorKind = when {
        code != 0 -> subsonicCodes[code] ?: ErrorKind.UNKNOWN
        httpStatus == HTTP_TOO_MANY_REQUESTS -> ErrorKind.RATE_LIMITED
        httpStatus == HTTP_NOT_IMPLEMENTED -> ErrorKind.NOT_IMPLEMENTED
        else -> ErrorKind.GENERIC
    }

    /** The kind of a `/ut/v1` problem `code`. */
    fun problemKind(code: String): ErrorKind = problemCodes[code] ?: ErrorKind.UNKNOWN

    /** [error] as a failure: credential problems (or any 401) are [TunesResult.Unauthorized]. */
    fun failure(error: TunesError, httpStatus: Int): TunesResult.Failure =
        if (error.kind.isAuthentication || httpStatus == HTTP_UNAUTHORIZED) {
            TunesResult.Unauthorized(error, httpStatus)
        } else {
            TunesResult.ApiError(error, httpStatus)
        }

    /**
     * A `Retry-After` header: delay seconds (what the server sends) or an HTTP date, measured
     * against [clock]. Null when absent or unreadable; never negative.
     */
    fun retryAfter(header: String?, clock: Clock): Duration? {
        val value = header?.trim().orEmpty()
        val seconds = value.toLongOrNull()
        return when {
            value.isEmpty() -> null
            seconds != null -> Duration.ofSeconds(seconds.coerceAtLeast(0))
            else -> untilHttpDate(value, clock)
        }
    }

    private fun untilHttpDate(value: String, clock: Clock): Duration? = try {
        val at = ZonedDateTime.parse(value, DateTimeFormatter.RFC_1123_DATE_TIME).toInstant()
        Duration.between(clock.instant(), at).takeUnless { it.isNegative } ?: Duration.ZERO
    } catch (_: DateTimeParseException) {
        null
    }
}
