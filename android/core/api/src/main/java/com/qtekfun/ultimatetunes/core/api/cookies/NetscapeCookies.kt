// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.api.cookies

import java.time.Duration
import java.time.Instant

/**
 * Builds the Netscape `cookies.txt` the server wants (`PUT /ut/v1/youtube-cookies`) from what
 * Android's `CookieManager.getCookie(url)` returns: one header string, `name=value; name=value`.
 *
 * Known limitation of that source: `getCookie` returns only names and values, never the
 * attributes (domain, path, expiry, flags). So each line is derived, not copied:
 * - the domain is the one the caller says the cookies belong to (`.youtube.com`, `.google.com`),
 *   with the include-subdomains flag TRUE, because a cookie that a host-only cookie jar would
 *   keep is still sent to that host by yt-dlp;
 * - the path is `/` and the flag `secure` is TRUE (every URL asked is https, and HTTPS-only is
 *   what Google sets on session cookies);
 * - the expiry is [SESSION_LIFETIME] after `now` for every cookie, because the real one is
 *   unknown (a Netscape expiry of 0 is read by some parsers as already expired);
 * - `__Host-` cookies are host-only by definition, so they get the exact host and flag FALSE.
 *
 * The result is a secret: never log it, never put it in a `Bundle` or `Intent`.
 */
object NetscapeCookies {
    private const val LIFETIME_DAYS = 365L

    const val HEADER = "# Netscape HTTP Cookie File"

    /** The server refuses larger bodies; output stops before that (browsers cap far below). */
    const val MAX_BYTES = 262_144 // 256 KiB

    /** The expiry given to every cookie, since `CookieManager` does not tell the real one. */
    val SESSION_LIFETIME: Duration = Duration.ofDays(LIFETIME_DAYS)

    private const val HOST_PREFIX = "__Host-"

    /** Cookies that only a signed-in Google session sets (what yt-dlp builds its auth from). */
    private val SESSION_COOKIES = setOf("SAPISID", "__Secure-3PAPISID", "__Secure-3PSID")

    /**
     * One `CookieManager.getCookie` answer.
     *
     * @property cookieHeader `name=value; name=value`, or null when the jar had none.
     * @property domain the cookie domain to write, with the leading dot (`.youtube.com`).
     * @property host the host that was asked (`www.youtube.com`), used for `__Host-` cookies.
     */
    class Source(val cookieHeader: String?, val domain: String, val host: String) {
        // The header holds secrets: keep them out of any accidental toString into a log.
        override fun toString(): String = "Source(domain=$domain, host=$host)"
    }

    /** `name=value` pairs of a `Cookie` header; pieces without a name or a `=` are dropped. */
    fun parseHeader(header: String?): List<Pair<String, String>> = header.orEmpty()
        .split(';')
        .mapNotNull { piece ->
            val trimmed = piece.trim()
            val eq = trimmed.indexOf('=')
            val name = if (eq > 0) trimmed.substring(0, eq).trim() else ""
            if (name.isEmpty() || !isSafe(name)) {
                null
            } else {
                val value = trimmed.substring(eq + 1)
                value.takeIf(::isSafe)?.let { name to it }
            }
        }

    /**
     * Whether [cookieHeader] (read for `www.youtube.com`) holds a signed-in session, i.e. a
     * `SAPISID`-type cookie. Plain visits to YouTube never set one.
     */
    fun hasSession(cookieHeader: String?): Boolean =
        parseHeader(cookieHeader).any { it.first in SESSION_COOKIES }

    /**
     * The `cookies.txt` for [sources] (earlier sources win when a domain and name repeat), or null
     * when there is no cookie at all. Every cookie expires at `now + [SESSION_LIFETIME]`.
     */
    fun serialize(sources: List<Source>, now: Instant): String? {
        val expiry = now.plus(SESSION_LIFETIME).epochSecond
        val seen = HashSet<String>()
        val out = StringBuilder(HEADER).append('\n')
        var count = 0
        for (source in sources) {
            for ((name, value) in parseHeader(source.cookieHeader)) {
                val hostOnly = name.startsWith(HOST_PREFIX)
                val domain = if (hostOnly) source.host else source.domain
                if (!seen.add("$domain\t$name")) continue
                val line = listOf(
                    domain,
                    if (hostOnly) "FALSE" else "TRUE",
                    "/",
                    "TRUE",
                    expiry.toString(),
                    name,
                    value
                ).joinToString("\t")
                if (out.length + line.length + 1 > MAX_BYTES) return finish(out, count)
                out.append(line).append('\n')
                count++
            }
        }
        return finish(out, count)
    }

    private fun finish(out: StringBuilder, count: Int): String? =
        if (count == 0) null else out.toString()

    /** Tabs and line breaks would break the format; Google's cookies never contain them. */
    private fun isSafe(text: String): Boolean = text.none { it == '\t' || it == '\n' || it == '\r' }
}
