// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.youtube

import android.annotation.SuppressLint
import android.webkit.CookieManager
import android.webkit.RenderProcessGoneDetail
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.viewinterop.AndroidView
import androidx.webkit.UserAgentMetadata
import androidx.webkit.WebSettingsCompat
import androidx.webkit.WebViewFeature
import java.io.ByteArrayInputStream

/**
 * A WebView on Google's sign-in, kept to Google and YouTube hosts ([isAllowedPage],
 * [isAllowedResource]). It reads nothing itself: the view model asks the cookie jar when a page
 * finishes at a YouTube host.
 */
@SuppressLint("SetJavaScriptEnabled") // Google's sign-in does not work without JavaScript.
@Composable
internal fun YoutubeLoginWebView(
    navigate: NavigateRequest?,
    events: LoginWebViewEvents,
    modifier: Modifier = Modifier
) {
    val current by rememberUpdatedState(events)
    var webView by remember { mutableStateOf<WebView?>(null) }
    // The sign-in asks for a page (YouTube Music once Google signed in, or the sign-in again).
    LaunchedEffect(navigate?.id, webView) {
        val request = navigate
        val view = webView
        if (request != null && view != null) {
            view.loadUrl(request.url)
            current.navigated(request.id)
        }
    }
    AndroidView(
        modifier = modifier,
        factory = { context ->
            WebView(context).apply {
                configureLoginWebView(this)
                webViewClient = LoginClient(
                    pageSeen = { host -> current.pageFinished(host) },
                    loadFailed = { current.loadFailed() },
                    blocked = { host -> current.blocked(host) }
                )
                loadUrl(YOUTUBE_LOGIN_URL)
                webView = this
            }
        },
        onRelease = { view ->
            webView = null
            view.stopLoading()
            view.destroy()
            current.released()
        }
    )
}

/**
 * The settings of the sign-in WebView: JavaScript and storage on (Google's pages need them), no
 * file access, a plain mobile Chrome user agent, and client hints that say the same (the system
 * ones list "Android WebView").
 */
@SuppressLint("SetJavaScriptEnabled")
private fun configureLoginWebView(view: WebView) {
    val settings = view.settings
    settings.javaScriptEnabled = true
    settings.domStorageEnabled = true
    settings.allowFileAccess = false
    settings.allowContentAccess = false
    settings.javaScriptCanOpenWindowsAutomatically = false
    settings.mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
    settings.safeBrowsingEnabled = true
    val chrome = loginChromeVersion(settings.userAgentString)
    settings.userAgentString = loginUserAgent(settings.userAgentString)
    if (WebViewFeature.isFeatureSupported(WebViewFeature.USER_AGENT_METADATA)) {
        WebSettingsCompat.setUserAgentMetadata(settings, loginUserAgentMetadata(chrome))
    }
    CookieManager.getInstance().setAcceptCookie(true)
    CookieManager.getInstance().setAcceptThirdPartyCookies(view, true)
}

private fun loginUserAgentMetadata(chromeFull: String): UserAgentMetadata =
    UserAgentMetadata.Builder()
        .setBrandVersionList(
            loginBrands(chromeFull).map {
                UserAgentMetadata.BrandVersion.Builder()
                    .setBrand(it.name)
                    .setMajorVersion(it.major)
                    .setFullVersion(it.full)
                    .build()
            }
        )
        .setFullVersion(chromeFull)
        .setMobile(true)
        .build()

private const val HTTP_FORBIDDEN = 403

// androidx.webkit's MissingOnRenderProcessGone reports every WebViewClient() constructor call,
// including this superclass call, even though the class overrides onRenderProcessGone below.
@SuppressLint("MissingOnRenderProcessGone")
private class LoginClient(
    private val pageSeen: (String?) -> Unit,
    private val loadFailed: () -> Unit,
    private val blocked: (String?) -> Unit
) : WebViewClient() {
    override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
        val allowed = isAllowedPage(request.url)
        if (!allowed) {
            blocked(request.url.host)
            loadFailed()
        }
        return !allowed
    }

    override fun shouldInterceptRequest(
        view: WebView,
        request: WebResourceRequest
    ): WebResourceResponse? = if (isAllowedResource(request.url)) {
        null
    } else {
        blocked(request.url.host)
        WebResourceResponse(
            "text/plain",
            "utf-8",
            HTTP_FORBIDDEN,
            "Blocked",
            emptyMap(),
            ByteArrayInputStream(ByteArray(0))
        )
    }

    override fun onReceivedError(
        view: WebView,
        request: WebResourceRequest,
        error: WebResourceError
    ) {
        if (request.isForMainFrame) loadFailed()
    }

    /**
     * The WebView's render process died (out of memory, a crash): without an answer here the whole
     * app goes down. The view is no longer usable, so say that the page failed; "Continue"
     * still reads the jar, and closing the screen and signing in again starts afresh.
     */
    override fun onRenderProcessGone(view: WebView, detail: RenderProcessGoneDetail): Boolean {
        loadFailed()
        return true
    }

    // Any of these can be the moment the session cookies appear: look at the jar on each.
    override fun onPageFinished(view: WebView, url: String?) = pageSeen(hostOf(url))

    override fun onPageCommitVisible(view: WebView, url: String?) = pageSeen(hostOf(url))

    override fun doUpdateVisitedHistory(view: WebView, url: String?, isReload: Boolean) =
        pageSeen(hostOf(url))

    private fun hostOf(url: String?): String? = url?.let(android.net.Uri::parse)?.host
}
