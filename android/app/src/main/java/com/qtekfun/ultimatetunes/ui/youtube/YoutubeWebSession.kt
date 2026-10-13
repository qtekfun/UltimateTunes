// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.youtube

import android.webkit.CookieManager
import android.webkit.WebStorage
import com.qtekfun.ultimatetunes.core.api.cookies.NetscapeCookies
import javax.inject.Inject
import javax.inject.Singleton

/** The WebView's cookie jar, as far as the sign-in needs it. Nothing here is kept by the app. */
interface YoutubeWebSession {
    /** What the jar holds now for youtube.com (first) and Google. Secrets: never log. */
    fun cookieSources(): List<NetscapeCookies.Source>

    /** Forgets every cookie and all web storage, on disk too. */
    fun clear()
}

/** [YoutubeWebSession] over `android.webkit.CookieManager`. */
@Singleton
class CookieManagerSession @Inject constructor() : YoutubeWebSession {
    override fun cookieSources(): List<NetscapeCookies.Source> {
        val manager = CookieManager.getInstance()
        return SOURCES.map { (host, domain) ->
            NetscapeCookies.Source(manager.getCookie("https://$host"), domain, host)
        }
    }

    override fun clear() {
        val manager = CookieManager.getInstance()
        manager.removeAllCookies(null)
        manager.flush()
        WebStorage.getInstance().deleteAllData()
    }

    private companion object {
        // youtube.com first: its cookies win when a name repeats.
        val SOURCES = listOf(
            "www.youtube.com" to ".youtube.com",
            "music.youtube.com" to ".youtube.com",
            "accounts.google.com" to ".google.com",
            "www.google.com" to ".google.com"
        )
    }
}
