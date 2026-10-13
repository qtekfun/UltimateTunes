// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.youtube

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class YoutubeLoginTest {
    @Test
    fun `pages are https on Google and YouTube only`() {
        assertTrue(isAllowedPage("https", "accounts.google.com"))
        assertTrue(isAllowedPage("https", "www.youtube.com"))
        assertTrue(isAllowedPage("https", "YouTube.com"))
        assertTrue(isAllowedPage("https", "m.youtube.com"))
        assertFalse(isAllowedPage("http", "accounts.google.com"))
        assertFalse(isAllowedPage("https", "evil-google.com"))
        assertFalse(isAllowedPage("https", "google.com.evil.example"))
        assertTrue(isAllowedPage("https", "myaccount.google.com"))
        assertTrue(isAllowedPage("https", "consent.google.com"))
        assertTrue(isAllowedPage("https", "www.google.com"))
        assertFalse(isAllowedPage("https", "sites.google.com"))
        assertFalse(isAllowedPage("https", "evilgoogle.com"))
        assertFalse(isAllowedPage("https", "storage.googleapis.com"))
        assertFalse(isAllowedPage("https", "docs.google.com"))
        assertFalse(isAllowedPage("https", "gstatic.com")) // a resource host, not a page
        assertFalse(isAllowedPage("https", null))
        assertFalse(isAllowedPage(null, "www.youtube.com"))
        assertFalse(isAllowedPage("javascript", "www.youtube.com"))
    }

    @Test
    fun `resources also come from the Google static hosts`() {
        assertTrue(isAllowedResource("https", "www.gstatic.com"))
        assertTrue(isAllowedResource("https", "lh3.googleusercontent.com"))
        assertTrue(isAllowedResource("https", "i.ytimg.com"))
        assertTrue(isAllowedResource("https", "accounts.google.com"))
        assertTrue(isAllowedResource("https", "storage.googleapis.com"))
        assertTrue(isAllowedResource("https", "apis.google.com"))
        assertFalse(isAllowedResource("http", "www.gstatic.com"))
        assertFalse(isAllowedResource("https", "tracker.example.com"))
        assertFalse(isAllowedResource("https", "notgstatic.com"))
        assertFalse(isAllowedResource("https", null))
    }

    @Test
    fun `the session is read at YouTube hosts only`() {
        assertTrue(isYoutubeHost("www.youtube.com"))
        assertTrue(isYoutubeHost("youtube.com"))
        assertFalse(isYoutubeHost("accounts.google.com"))
        assertFalse(isYoutubeHost("youtube.com.evil.example"))
        assertFalse(isYoutubeHost(null))
    }

    @Test
    fun `the login starts on Google and continues to YouTube`() {
        assertTrue(YOUTUBE_LOGIN_URL.startsWith("https://accounts.google.com/"))
        assertTrue(YOUTUBE_LOGIN_URL.contains("continue=https%3A%2F%2Fwww.youtube.com%2F"))
    }

    @Test
    fun `the user agent loses the WebView markers`() {
        val webView =
            "Mozilla/5.0 (Linux; Android 14; Pixel 8 Build/AP1A; wv) AppleWebKit/537.36 " +
                "(KHTML, like Gecko) Version/4.0 Chrome/130.0.0.0 Mobile Safari/537.36"

        assertEquals(
            "Mozilla/5.0 (Linux; Android 14; Pixel 8 Build/AP1A) AppleWebKit/537.36 " +
                "(KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36",
            loginUserAgent(webView)
        )
        assertEquals("Chrome/130", loginUserAgent("Chrome/130"))
    }
}
