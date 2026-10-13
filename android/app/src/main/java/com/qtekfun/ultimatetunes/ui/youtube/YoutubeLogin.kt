// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.youtube

import android.net.Uri

/*
 * The rules of the "Sign in to YouTube" WebView (SPEC section 11, D14). This is the one place
 * where the app itself contacts Google, only when the user asks for it; the cookies it yields go
 * to the user's own server and nowhere else.
 */

/** Google's sign-in page for YouTube; it continues to youtube.com once signed in. */
const val YOUTUBE_LOGIN_URL =
    "https://accounts.google.com/ServiceLogin?service=youtube&continue=https%3A%2F%2Fwww.youtube.com%2F"

/** Hosts (and all their subdomains) the user may be navigated to: the sign-in itself. */
private val PAGE_DOMAINS = listOf("google.com", "youtube.com")

/** Extra hosts the sign-in pages load scripts, styles, fonts and images from. */
private val RESOURCE_DOMAINS = listOf(
    "gstatic.com",
    "googleapis.com",
    "googleusercontent.com",
    "ggpht.com",
    "ytimg.com"
)

/** True when [host] is [domain] or one of its subdomains. */
private fun isWithin(host: String, domain: String): Boolean =
    host == domain || host.endsWith(".$domain")

/** Whether [host] is a YouTube host (where the signed-in session is read). */
fun isYoutubeHost(host: String?): Boolean =
    host != null && isWithin(host.lowercase(), "youtube.com")

/** Whether the top-level page may navigate to [url]: https on a Google or YouTube host only. */
fun isAllowedPage(url: Uri?): Boolean = isAllowedPage(url?.scheme, url?.host)

internal fun isAllowedPage(scheme: String?, host: String?): Boolean =
    scheme == "https" && host != null && PAGE_DOMAINS.any { isWithin(host.lowercase(), it) }

/** Whether a sub-resource (script, image...) may be fetched from [url]. */
fun isAllowedResource(url: Uri?): Boolean = isAllowedResource(url?.scheme, url?.host)

internal fun isAllowedResource(scheme: String?, host: String?): Boolean =
    isAllowedPage(scheme, host) ||
        (
            scheme == "https" && host != null &&
                RESOURCE_DOMAINS.any { isWithin(host.lowercase(), it) }
            )

/**
 * The user agent for the login: the WebView's own with the markers that make Google refuse
 * embedded browsers removed (`; wv` and `Version/x.y`), so it reads as the system Chrome.
 */
fun loginUserAgent(default: String): String = default
    .replace("; wv)", ")")
    .replace(Regex("""\s?Version/\d+(\.\d+)*"""), "")
