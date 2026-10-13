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

/** Pages the user may be navigated to: exactly these Google hosts (no other google.com host). */
private val PAGE_HOSTS = setOf(
    "accounts.google.com",
    "myaccount.google.com",
    "consent.google.com",
    "www.google.com",
    "google.com"
)

/** YouTube hosts (all subdomains: www, m, accounts, consent) are pages too. */
private const val YOUTUBE = "youtube.com"

/** Domains (and subdomains) sign-in pages load sub-resources from; never navigable pages. */
private val RESOURCE_DOMAINS = listOf(
    "google.com",
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
fun isYoutubeHost(host: String?): Boolean = host != null && isWithin(host.lowercase(), YOUTUBE)

/** Whether the top-level page may navigate to [url]: https on a Google or YouTube host only. */
fun isAllowedPage(url: Uri?): Boolean = isAllowedPage(url?.scheme, url?.host)

internal fun isAllowedPage(scheme: String?, host: String?): Boolean =
    scheme == "https" && host != null &&
        host.lowercase().let { it in PAGE_HOSTS || isWithin(it, YOUTUBE) }

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
