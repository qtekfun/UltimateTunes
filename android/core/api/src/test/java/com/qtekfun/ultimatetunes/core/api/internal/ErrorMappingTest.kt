// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.api.internal

import com.qtekfun.ultimatetunes.core.api.ErrorKind
import com.qtekfun.ultimatetunes.core.api.TunesError
import com.qtekfun.ultimatetunes.core.api.TunesResult
import java.time.Clock
import java.time.Duration
import java.time.Instant
import java.time.ZoneOffset
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.params.ParameterizedTest
import org.junit.jupiter.params.provider.CsvSource

/** The client side of contracts/errors.md: every OpenSubsonic code and every problem code. */
class ErrorMappingTest {
    @ParameterizedTest(name = "OpenSubsonic {0} with HTTP {1} is {2}")
    @CsvSource(
        "0, 200, GENERIC",
        "0, 429, RATE_LIMITED",
        "0, 501, NOT_IMPLEMENTED",
        "10, 200, MISSING_PARAMETER",
        "20, 200, CLIENT_TOO_OLD",
        "30, 200, SERVER_TOO_OLD",
        "40, 200, AUTHENTICATION_FAILED",
        "41, 200, TOKEN_AUTH_NOT_SUPPORTED",
        "42, 200, TOKEN_AUTH_NOT_SUPPORTED",
        "43, 200, CONFLICTING_AUTH",
        "44, 200, INVALID_API_KEY",
        "50, 200, FORBIDDEN",
        "70, 200, NOT_FOUND",
        "99, 200, UNKNOWN"
    )
    fun `OpenSubsonic codes`(code: Int, httpStatus: Int, kind: ErrorKind) {
        assertEquals(kind, ErrorMapping.subsonicKind(code, httpStatus))
    }

    @ParameterizedTest(name = "problem {0} is {1}")
    @CsvSource(
        "missing_parameter, MISSING_PARAMETER",
        "invalid_parameter, INVALID_PARAMETER",
        "invalid_id, INVALID_ID",
        "authentication_required, AUTHENTICATION_REQUIRED",
        "authentication_failed, AUTHENTICATION_FAILED",
        "second_factor_required, SECOND_FACTOR_REQUIRED",
        "conflicting_auth, CONFLICTING_AUTH",
        "invalid_api_key, INVALID_API_KEY",
        "account_disabled, ACCOUNT_DISABLED",
        "forbidden, FORBIDDEN",
        "not_found, NOT_FOUND",
        "conflict, CONFLICT",
        "feature_disabled, FEATURE_DISABLED",
        "unsupported_url, UNSUPPORTED_URL",
        "payload_too_large, PAYLOAD_TOO_LARGE",
        "rate_limited, RATE_LIMITED",
        "upstream_unavailable, UPSTREAM_UNAVAILABLE",
        "download_failed, DOWNLOAD_FAILED",
        "not_implemented, NOT_IMPLEMENTED",
        "internal_error, INTERNAL",
        "something_new, UNKNOWN"
    )
    fun `problem codes`(code: String, kind: ErrorKind) {
        assertEquals(kind, ErrorMapping.problemKind(code))
    }

    @Test
    fun `credential errors and any 401 are Unauthorized, the rest ApiError`() {
        ErrorKind.entries.forEach { kind ->
            val result = ErrorMapping.failure(TunesError(kind), 200)
            if (kind.isAuthentication) {
                assertTrue(result is TunesResult.Unauthorized, "$kind")
            } else {
                assertTrue(result is TunesResult.ApiError, "$kind")
            }
        }
        assertTrue(
            ErrorMapping.failure(TunesError(ErrorKind.UNKNOWN), 401) is TunesResult.Unauthorized
        )
        val authKinds = ErrorKind.entries.filter { it.isAuthentication }.toSet()
        assertEquals(
            setOf(
                ErrorKind.AUTHENTICATION_REQUIRED,
                ErrorKind.AUTHENTICATION_FAILED,
                ErrorKind.SECOND_FACTOR_REQUIRED,
                ErrorKind.TOKEN_AUTH_NOT_SUPPORTED,
                ErrorKind.CONFLICTING_AUTH,
                ErrorKind.INVALID_API_KEY,
                ErrorKind.ACCOUNT_DISABLED
            ),
            authKinds
        )
    }

    @Test
    fun `Retry-After in seconds or as an HTTP date`() {
        val clock = Clock.fixed(Instant.parse("2026-10-12T08:00:00Z"), ZoneOffset.UTC)
        assertEquals(Duration.ofSeconds(60), ErrorMapping.retryAfter("60", clock))
        assertEquals(Duration.ofSeconds(60), ErrorMapping.retryAfter(" 60 ", clock))
        assertEquals(Duration.ZERO, ErrorMapping.retryAfter("-5", clock))
        assertEquals(
            Duration.ofSeconds(90),
            ErrorMapping.retryAfter("Mon, 12 Oct 2026 08:01:30 GMT", clock)
        )
        assertEquals(Duration.ZERO, ErrorMapping.retryAfter("Mon, 12 Oct 2026 07:00:00 GMT", clock))
        assertNull(ErrorMapping.retryAfter("soon", clock))
        assertNull(ErrorMapping.retryAfter("", clock))
        assertNull(ErrorMapping.retryAfter(null, clock))
    }
}
