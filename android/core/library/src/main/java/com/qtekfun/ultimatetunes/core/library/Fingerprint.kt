// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.library

import com.qtekfun.ultimatetunes.core.api.ServerConfig
import java.security.MessageDigest

/**
 * Tells one connection from another without storing its key: a hash of the server's address and
 * the API key (256 random bits, so the hash gives nothing away).
 */
internal fun fingerprintOf(config: ServerConfig): String = MessageDigest.getInstance("SHA-256")
    .digest("${config.root}\n${config.apiKey.value}".encodeToByteArray())
    .joinToString("") { "%02x".format(it) }
