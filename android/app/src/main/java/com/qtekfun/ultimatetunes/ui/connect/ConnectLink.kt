// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.connect

import com.qtekfun.ultimatetunes.core.api.ServerConfig
import com.qtekfun.ultimatetunes.core.api.model.ApiKeySecret
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.charset.CharacterCodingException
import java.nio.charset.CodingErrorAction
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull

/** Why a connect link (the admin panel's QR code) cannot be used. */
enum class ConnectLinkError {
    /** Not an `ultimatetunes://connect?…` link, or not exactly `url` and `key`, or garbled. */
    MALFORMED,

    /** The `url` parameter is not a server address. */
    INVALID_URL,

    /** The `url` parameter is a plain `http://` address, which this build refuses. */
    INSECURE_URL,

    /** The `key` parameter does not have the shape of an UltimateTunes key. */
    INVALID_KEY
}

/** What a connect link holds once parsed: the server root and the key, or why it was refused. */
sealed interface ConnectLinkParse {
    /** A well-formed link. [toString] never shows the key ([ApiKeySecret] redacts itself). */
    data class Valid(val url: HttpUrl, val key: ApiKeySecret) : ConnectLinkParse

    data class Invalid(val error: ConnectLinkError) : ConnectLinkParse
}

/**
 * The parser of the admin panel's QR payload (contracts/ids.md, "App connect QR code"):
 * `ultimatetunes://connect?url=<percent-encoded server base URL>&key=<the API key>`.
 *
 * Strict on purpose, since anyone can craft such a link: only that scheme and host (lower case,
 * no path, no fragment), exactly the parameters `url` and `key`, once each; `url` an absolute
 * `https://` address (plain `http://` only where [CleartextPolicy] allows it, i.e. debug builds
 * and the emulator's host) without credentials, query or fragment; `key` in the API key format.
 * Never logs anything.
 */
object ConnectLink {
    /** Longer links are refused unread: the panel's own are under 250 characters. */
    const val MAX_LENGTH = 1024

    private const val PREFIX = "ultimatetunes://connect?"
    private const val URL_PARAM = "url"
    private const val KEY_PARAM = "key"
    private const val HEX_RADIX = 16
    private const val HEX_PAIR = 2
    private const val ESCAPE_LENGTH = 1 + HEX_PAIR
    private const val HEX_DIGITS = "0123456789abcdefABCDEF"
    private val PRINTABLE = '!'..'~'

    fun parse(link: String, cleartext: CleartextPolicy): ConnectLinkParse {
        val params = if (link.length <= MAX_LENGTH && link.startsWith(PREFIX)) {
            queryOf(link.substring(PREFIX.length))
        } else {
            null
        }
        val url = params?.get(URL_PARAM)
        val key = params?.get(KEY_PARAM)
        return when {
            url == null || key == null -> invalid(ConnectLinkError.MALFORMED)
            else -> validate(url, key, cleartext)
        }
    }

    private fun validate(
        rawUrl: String,
        key: String,
        cleartext: CleartextPolicy
    ): ConnectLinkParse {
        val url = rawUrl.takeIf { it.none(Char::isWhitespace) }?.toHttpUrlOrNull()
        return when {
            url == null || !isPlainRoot(url) -> invalid(ConnectLinkError.INVALID_URL)

            !url.isHttps && !cleartext.isPermitted(url.host) ->
                invalid(ConnectLinkError.INSECURE_URL)

            !ApiKeySecret.isWellFormed(key) -> invalid(ConnectLinkError.INVALID_KEY)

            else -> ConnectLinkParse.Valid(ServerConfig.rootOf(url), ApiKeySecret(key))
        }
    }

    private fun isPlainRoot(url: HttpUrl): Boolean =
        url.username.isEmpty() && url.password.isEmpty() &&
            url.encodedQuery == null && url.encodedFragment == null

    private fun invalid(error: ConnectLinkError) = ConnectLinkParse.Invalid(error)

    /**
     * The decoded `url` and `key` of [query], or null unless it holds exactly those two, once
     * each, correctly percent-encoded (UTF-8), with no fragment.
     */
    private fun queryOf(query: String): Map<String, String>? {
        val parts = query.takeUnless { '#' in it }?.split('&').orEmpty()
        val params = parts.mapNotNull(::paramOf)
        val exactlyBoth = parts.size == 2 && params.size == 2 &&
            params.map { it.first }.toSet().size == 2
        return params.toMap().takeIf { exactlyBoth }
    }

    /** `url=…` or `key=…` decoded, or null for any other name or a broken value. */
    private fun paramOf(part: String): Pair<String, String>? {
        val name = part.substringBefore('=', missingDelimiterValue = "")
        val value = percentDecode(part.substringAfter('=', missingDelimiterValue = ""))
        return if (value != null &&
            (name == URL_PARAM || name == KEY_PARAM)
        ) {
            name to value
        } else {
            null
        }
    }

    /** Strict percent-decoding: `%` needs two hex digits, `+` stays `+`, bytes must be UTF-8. */
    internal fun percentDecode(encoded: String): String? = percentBytes(encoded)
        ?.let(::utf8OrNull)
        ?.takeIf { decoded -> decoded.none { it.isISOControl() } }

    /** The bytes [encoded] stands for, or null if it holds a bad escape or a raw non-printable. */
    private fun percentBytes(encoded: String): ByteArray? {
        val bytes = ByteArrayOutputStream(encoded.length)
        var ok = true
        var i = 0
        while (ok && i < encoded.length) {
            val c = encoded[i]
            if (c == '%') {
                val byte = hexByteAt(encoded, i + 1)
                ok = byte != null
                bytes.write(byte ?: 0)
                i += ESCAPE_LENGTH
            } else {
                ok = c in PRINTABLE
                bytes.write(c.code)
                i++
            }
        }
        return bytes.toByteArray().takeIf { ok }
    }

    private fun hexByteAt(text: String, at: Int): Int? = text
        .substring(minOf(at, text.length), minOf(at + HEX_PAIR, text.length))
        .takeIf { pair -> pair.length == HEX_PAIR && pair.all { it in HEX_DIGITS } }
        ?.toInt(HEX_RADIX)

    private fun utf8OrNull(bytes: ByteArray): String? = try {
        Charsets.UTF_8.newDecoder()
            .onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT)
            .decode(ByteBuffer.wrap(bytes))
            .toString()
    } catch (_: CharacterCodingException) {
        null
    }
}
