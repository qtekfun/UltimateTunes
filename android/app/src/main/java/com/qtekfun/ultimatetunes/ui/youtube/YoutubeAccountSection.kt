// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.youtube

import android.annotation.SuppressLint
import android.webkit.CookieManager
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.compose.ui.window.SecureFlagPolicy
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.ui.designsystem.ErrorState
import com.qtekfun.ultimatetunes.ui.designsystem.LoadingState
import com.qtekfun.ultimatetunes.ui.designsystem.SectionHeader
import com.qtekfun.ultimatetunes.ui.settings.Detail
import com.qtekfun.ultimatetunes.ui.settings.formatDate
import com.qtekfun.ultimatetunes.ui.theme.Dimens
import java.io.ByteArrayInputStream

/** Test tags of the YouTube account section. */
const val YOUTUBE_SIGN_IN_TAG = "youtube.signIn"
const val YOUTUBE_SIGN_OUT_TAG = "youtube.signOut"
const val YOUTUBE_WARNING_CONTINUE_TAG = "youtube.warningContinue"
const val YOUTUBE_CONTINUE_TAG = "youtube.continue"
const val YOUTUBE_LOGIN_PROBLEM_TAG = "youtube.loginProblem"

/** What the YouTube account section can do. */
data class YoutubeActions(
    val retry: () -> Unit = {},
    val startSignIn: () -> Unit = {},
    val confirmWarning: () -> Unit = {},
    val cancel: () -> Unit = {},
    val pageFinished: (String?) -> Unit = {},
    val webViewReleased: () -> Unit = {},
    val continueNow: () -> Unit = {},
    val loadFailed: () -> Unit = {},
    val remove: () -> Unit = {}
)

/** Settings, "YouTube account" (D14): the status, sign in (WebView) and sign out. */
@Composable
internal fun YoutubeAccountSection(state: YoutubeAccountUiState, actions: YoutubeActions) {
    Column {
        SectionHeader(stringResource(R.string.youtube_title))
        Text(
            text = stringResource(R.string.youtube_help),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = Dimens.ScreenMargin)
        )
        when (val status = state.status) {
            YoutubeStatus.Loading -> LoadingState()
            YoutubeStatus.NotAdmin -> Note(stringResource(R.string.youtube_not_admin))
            is YoutubeStatus.Failed -> ErrorState(status.error, actions.retry)
            is YoutubeStatus.Ready -> ReadyContent(status, actions)
        }
    }
    YoutubeDialogs(state, actions)
}

@Composable
private fun ReadyContent(status: YoutubeStatus.Ready, actions: YoutubeActions) {
    val value = status.value
    Detail(
        stringResource(R.string.youtube_title),
        if (value.configured) {
            val count = value.cookieCount
            listOfNotNull(
                stringResource(R.string.youtube_signed_in),
                value.setAt?.let { stringResource(R.string.youtube_signed_since, formatDate(it)) },
                count?.let { pluralStringResource(R.plurals.youtube_cookies, it, it) }
            ).joinToString(" · ")
        } else {
            stringResource(R.string.youtube_not_signed_in)
        }
    )
    if (!value.available) {
        Note(stringResource(R.string.youtube_unavailable))
        return
    }
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = Dimens.ScreenMargin, vertical = Dimens.SpaceS),
        verticalArrangement = Arrangement.spacedBy(Dimens.SpaceS)
    ) {
        OutlinedButton(
            onClick = actions.startSignIn,
            shape = Dimens.PillShape,
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(min = 48.dp)
                .testTag(YOUTUBE_SIGN_IN_TAG)
        ) {
            val label =
                if (value.configured) R.string.youtube_sign_in_again else R.string.youtube_sign_in
            Text(stringResource(label))
        }
        if (value.configured) {
            TextButton(
                onClick = actions.remove,
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = 48.dp)
                    .testTag(YOUTUBE_SIGN_OUT_TAG)
            ) {
                Text(
                    stringResource(R.string.youtube_sign_out),
                    color = MaterialTheme.colorScheme.error
                )
            }
        }
    }
}

@Composable
private fun Note(text: String) {
    Text(
        text = text,
        style = MaterialTheme.typography.bodyMedium,
        modifier = Modifier.padding(horizontal = Dimens.ScreenMargin, vertical = Dimens.SpaceS)
    )
}

@Composable
private fun YoutubeDialogs(state: YoutubeAccountUiState, actions: YoutubeActions) {
    when (state.phase) {
        YoutubePhase.IDLE -> Unit

        YoutubePhase.WARNING -> AlertDialog(
            onDismissRequest = actions.cancel,
            title = { Text(stringResource(R.string.youtube_warning_title)) },
            text = { Text(stringResource(R.string.youtube_warning_message)) },
            confirmButton = {
                TextButton(
                    onClick = actions.confirmWarning,
                    modifier = Modifier.testTag(YOUTUBE_WARNING_CONTINUE_TAG)
                ) { Text(stringResource(R.string.youtube_warning_continue)) }
            },
            dismissButton = {
                TextButton(onClick = actions.cancel) { Text(stringResource(R.string.cancel)) }
            }
        )

        YoutubePhase.SIGNING_IN -> YoutubeLoginDialog(state, actions)

        YoutubePhase.UPLOADING -> AlertDialog(
            onDismissRequest = {},
            confirmButton = {},
            title = { Text(stringResource(R.string.youtube_title)) },
            text = {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(Dimens.SpaceM)
                ) {
                    CircularProgressIndicator(modifier = Modifier.padding(end = Dimens.SpaceS))
                    Text(stringResource(R.string.youtube_uploading))
                }
            }
        )

        YoutubePhase.DONE -> MessageDialog(stringResource(R.string.youtube_done), actions.cancel)

        YoutubePhase.FAILED -> MessageDialog(
            stringResource(state.failure.messageRes()),
            actions.cancel
        )
    }
}

@Composable
private fun MessageDialog(message: String, onClose: () -> Unit) {
    AlertDialog(
        onDismissRequest = onClose,
        title = { Text(stringResource(R.string.youtube_failure_title)) },
        text = { Text(message) },
        confirmButton = {
            TextButton(onClick = onClose) { Text(stringResource(R.string.close)) }
        }
    )
}

private fun YoutubeFailure?.messageRes(): Int = when (this) {
    YoutubeFailure.NOT_ADMIN -> R.string.youtube_failure_not_admin
    YoutubeFailure.FEATURE_DISABLED -> R.string.youtube_failure_feature_disabled
    YoutubeFailure.REJECTED -> R.string.youtube_failure_rejected
    YoutubeFailure.TOO_LARGE -> R.string.youtube_failure_too_large
    YoutubeFailure.RATE_LIMITED -> R.string.youtube_failure_rate_limited
    YoutubeFailure.NETWORK -> R.string.youtube_failure_network
    YoutubeFailure.UNAUTHORIZED -> R.string.youtube_failure_unauthorized
    YoutubeFailure.SERVER, null -> R.string.youtube_failure_server
}

/**
 * The full-screen sign-in. Its window is secure (`FLAG_SECURE`): no screenshots, no screen
 * recording, no Recents thumbnail while the user types a password.
 */
@Composable
private fun YoutubeLoginDialog(state: YoutubeAccountUiState, actions: YoutubeActions) {
    Dialog(
        onDismissRequest = actions.cancel,
        properties = DialogProperties(
            usePlatformDefaultWidth = false,
            securePolicy = SecureFlagPolicy.SecureOn
        )
    ) {
        Surface(modifier = Modifier.fillMaxSize()) {
            Column(modifier = Modifier.fillMaxSize()) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = Dimens.ScreenMargin, vertical = Dimens.SpaceS),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        text = stringResource(R.string.youtube_login_title),
                        style = MaterialTheme.typography.titleMedium,
                        modifier = Modifier.weight(1f)
                    )
                    TextButton(onClick = actions.cancel) {
                        Text(stringResource(R.string.youtube_login_close))
                    }
                }
                LoginStatusLine(state)
                YoutubeLoginWebView(
                    onPageFinished = actions.pageFinished,
                    onLoadFailed = actions.loadFailed,
                    onReleased = actions.webViewReleased,
                    modifier = Modifier.fillMaxWidth().weight(1f)
                )
                Button(
                    onClick = actions.continueNow,
                    shape = Dimens.PillShape,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = Dimens.ScreenMargin, vertical = Dimens.SpaceS)
                        .heightIn(min = 48.dp)
                        .testTag(YOUTUBE_CONTINUE_TAG)
                ) { Text(stringResource(R.string.youtube_login_continue)) }
            }
        }
    }
}

@Composable
private fun LoginStatusLine(state: YoutubeAccountUiState) {
    val message = when {
        state.loadFailed -> R.string.youtube_login_load_failed
        state.noSession -> R.string.youtube_login_no_session
        else -> R.string.youtube_login_waiting
    }
    val waiting = message == R.string.youtube_login_waiting
    Text(
        text = stringResource(message),
        style = MaterialTheme.typography.bodyMedium,
        color = if (waiting) {
            MaterialTheme.colorScheme.onSurfaceVariant
        } else {
            MaterialTheme.colorScheme.error
        },
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = Dimens.ScreenMargin, vertical = Dimens.SpaceS)
            .testTag(YOUTUBE_LOGIN_PROBLEM_TAG)
    )
}

/**
 * A WebView on Google's sign-in, kept to Google and YouTube hosts ([isAllowedPage],
 * [isAllowedResource]). It reads nothing itself: the view model asks the cookie jar when a page
 * finishes at a YouTube host.
 */
@SuppressLint("SetJavaScriptEnabled") // Google's sign-in does not work without JavaScript.
@Composable
private fun YoutubeLoginWebView(
    onPageFinished: (String?) -> Unit,
    onLoadFailed: () -> Unit,
    onReleased: () -> Unit,
    modifier: Modifier = Modifier
) {
    val finished by rememberUpdatedState(onPageFinished)
    val released by rememberUpdatedState(onReleased)
    val failed by rememberUpdatedState(onLoadFailed)
    AndroidView(
        modifier = modifier,
        factory = { context ->
            WebView(context).apply {
                settings.javaScriptEnabled = true
                settings.domStorageEnabled = true
                settings.allowFileAccess = false
                settings.allowContentAccess = false
                settings.javaScriptCanOpenWindowsAutomatically = false
                settings.mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
                settings.safeBrowsingEnabled = true
                settings.userAgentString = loginUserAgent(settings.userAgentString)
                CookieManager.getInstance().setAcceptCookie(true)
                CookieManager.getInstance().setAcceptThirdPartyCookies(this, true)
                webViewClient = LoginClient(
                    pageSeen = { host -> finished(host) },
                    loadFailed = { failed() }
                )
                loadUrl(YOUTUBE_LOGIN_URL)
            }
        },
        onRelease = { webView ->
            webView.stopLoading()
            webView.destroy()
            released()
        }
    )
}

private const val HTTP_FORBIDDEN = 403

private class LoginClient(
    private val pageSeen: (String?) -> Unit,
    private val loadFailed: () -> Unit
) : WebViewClient() {
    override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean =
        !isAllowedPage(request.url).also { allowed -> if (!allowed) loadFailed() }

    override fun shouldInterceptRequest(
        view: WebView,
        request: WebResourceRequest
    ): WebResourceResponse? = if (isAllowedResource(request.url)) {
        null
    } else {
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

    // Any of these can be the moment the session cookies appear: look at the jar on each.
    override fun onPageFinished(view: WebView, url: String?) = pageSeen(hostOf(url))

    override fun onPageCommitVisible(view: WebView, url: String?) = pageSeen(hostOf(url))

    override fun doUpdateVisitedHistory(view: WebView, url: String?, isReload: Boolean) =
        pageSeen(hostOf(url))

    private fun hostOf(url: String?): String? = url?.let(android.net.Uri::parse)?.host
}
