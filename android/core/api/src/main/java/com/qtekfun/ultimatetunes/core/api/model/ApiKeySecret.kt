// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.api.model

import kotlinx.serialization.Serializable

/**
 * A full API key (`utk_` + 43 base64url characters, contracts/ids.md). Its [toString] never shows
 * the key, so it cannot leak through logs, crash reports or string templates by accident; read
 * [value] only to send or store it.
 */
@Serializable
@JvmInline
value class ApiKeySecret(val value: String) {
    /** The display prefix (`utk_` + 8 characters), the same as the server's `ApiKey.prefix`. */
    val prefix: String get() = value.take(PREFIX_LENGTH)

    override fun toString(): String = "ApiKeySecret(redacted)"

    companion object {
        private const val PREFIX_LENGTH = 12
        private val FORMAT = Regex("^utk_[A-Za-z0-9_-]{43}$")

        /** True when [candidate] has the shape of an API key (it may still be unknown or revoked). */
        fun isWellFormed(candidate: String): Boolean = FORMAT.matches(candidate)
    }
}
