// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.youtube

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.core.api.ErrorKind
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.cookies.NetscapeCookies
import com.qtekfun.ultimatetunes.core.api.model.YoutubeCookiesStatus
import com.qtekfun.ultimatetunes.ui.model.LoadError
import com.qtekfun.ultimatetunes.ui.model.toLoadError
import dagger.hilt.android.lifecycle.HiltViewModel
import java.time.Clock
import javax.inject.Inject
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

private const val YOUTUBE_DOMAIN = ".youtube.com"
private const val POLL_MS = 1_000L

/** Polling stops after 15 minutes; the Continue button stays. */
private const val MAX_POLLS = 900

/** What the server says about its YouTube session. */
sealed interface YoutubeStatus {
    data object Loading : YoutubeStatus

    data class Ready(val value: YoutubeCookiesStatus) : YoutubeStatus

    /** The key is not an admin's (HTTP 403): only admins manage the session. */
    data object NotAdmin : YoutubeStatus

    data class Failed(val error: LoadError) : YoutubeStatus
}

/** Where the sign-in flow is. */
enum class YoutubePhase {
    IDLE,

    /** The throwaway-account warning is shown. */
    WARNING,

    /** The WebView is open. */
    SIGNING_IN,

    /** The session is being sent to the server. */
    UPLOADING,

    /** Stored. */
    DONE,

    /** Something failed: see [YoutubeAccountUiState.failure]. */
    FAILED
}

/** Why a sign-in, upload or removal failed. */
enum class YoutubeFailure {
    NOT_ADMIN,

    /** The server has no `UT_YTDLP_COOKIES_KEY`. */
    FEATURE_DISABLED,

    /** The server refused the cookies (not a Netscape file). */
    REJECTED,
    TOO_LARGE,
    RATE_LIMITED,
    NETWORK,
    UNAUTHORIZED,
    SERVER
}

data class YoutubeAccountUiState(
    val status: YoutubeStatus = YoutubeStatus.Loading,
    val phase: YoutubePhase = YoutubePhase.IDLE,
    val failure: YoutubeFailure? = null,
    /** The user asked to continue but the jar holds no signed-in session (WebView screen). */
    val noSession: Boolean = false,
    /** The sign-in page itself could not be loaded (WebView screen). */
    val loadFailed: Boolean = false
)

/**
 * The "YouTube account" section of Settings (D14): the server's session status, the sign-in
 * through a WebView, and its removal. State machine of the sign-in:
 * `IDLE -> WARNING -> SIGNING_IN -> UPLOADING -> DONE | FAILED`, and back to `IDLE` on cancel
 * or dismiss.
 *
 * The cookies exist only inside [onPageFinished] and [upload]: read from the [session], turned
 * into text, the session wiped, the text sent with [TunesApi.setYoutubeCookies] and dropped. They are not in
 * the state, in saved state or in any log.
 */
@Suppress("TooManyFunctions") // One function per step of the sign-in and per failure mapping.
@HiltViewModel
class YoutubeAccountViewModel @Inject constructor(
    private val api: TunesApi,
    private val session: YoutubeWebSession,
    private val clock: Clock
) : ViewModel() {
    private val mutableState = MutableStateFlow(YoutubeAccountUiState())
    private var poller: Job? = null
    val state: StateFlow<YoutubeAccountUiState> = mutableState.asStateFlow()

    init {
        load()
    }

    /** Asks the server for the status (also the retry). */
    fun load() {
        mutableState.update { it.copy(status = YoutubeStatus.Loading) }
        viewModelScope.launch {
            val status = when (val result = api.youtubeCookiesStatus()) {
                is TunesResult.Success -> YoutubeStatus.Ready(result.value)
                is TunesResult.Failure -> result.toStatusFailure()
            }
            mutableState.update { it.copy(status = status) }
        }
    }

    /** "Sign in to YouTube" was tapped: shows the warning first. Only when the server can store. */
    fun startSignIn() {
        val status = mutableState.value.status as? YoutubeStatus.Ready ?: return
        if (!status.value.available || mutableState.value.phase.isBusy()) return
        mutableState.update { it.copy(phase = YoutubePhase.WARNING, failure = null) }
    }

    /** The warning was accepted: opens the WebView on a clean cookie jar. */
    fun confirmWarning() {
        if (mutableState.value.phase != YoutubePhase.WARNING) return
        session.clear()
        mutableState.update {
            it.copy(phase = YoutubePhase.SIGNING_IN, noSession = false, loadFailed = false)
        }
        startPolling()
    }

    /** Cancel or dismiss: back to idle, leaving nothing in the WebView. */
    fun cancel() {
        val phase = mutableState.value.phase
        if (phase == YoutubePhase.UPLOADING) return
        if (phase == YoutubePhase.SIGNING_IN) session.clear()
        poller?.cancel()
        mutableState.update {
            it.copy(
                phase = YoutubePhase.IDLE,
                failure = null,
                noSession = false,
                loadFailed = false
            )
        }
    }

    /**
     * The WebView shows a page (finished, committed or a history update): look at the jar now.
     * [host] is unused on purpose: the session can appear on any hop, so no page is skipped.
     */
    @Suppress("UNUSED_PARAMETER")
    fun onPageFinished(host: String?) {
        if (mutableState.value.phase != YoutubePhase.SIGNING_IN) return
        mutableState.update { it.copy(loadFailed = false) }
        captureNow()
    }

    /**
     * While the login is open the jar is looked at every second, so the capture does not depend
     * on any page event: YouTube may still be rendering when the session cookies already exist.
     */
    private fun startPolling() {
        poller?.cancel()
        poller = viewModelScope.launch {
            repeat(MAX_POLLS) {
                if (mutableState.value.phase != YoutubePhase.SIGNING_IN) return@launch
                delay(POLL_MS)
                captureNow()
            }
        }
    }

    /** "I'm signed in, continue": captures now, or says that there is no session. */
    fun continueNow() {
        if (mutableState.value.phase != YoutubePhase.SIGNING_IN) return
        if (!captureNow()) mutableState.update { it.copy(noSession = true) }
    }

    /** The sign-in page failed to load or a page of the flow was blocked. */
    fun onLoadFailed() {
        if (mutableState.value.phase != YoutubePhase.SIGNING_IN) return
        mutableState.update { it.copy(loadFailed = true) }
    }

    /** Reads the jar and, when it holds a signed-in session, wipes it and uploads. */
    private fun captureNow(): Boolean {
        val body = signedInCookies()
        if (body == null || mutableState.value.phase != YoutubePhase.SIGNING_IN) return false
        poller?.cancel()
        session.clear() // The WebView keeps nothing from here on.
        mutableState.update {
            it.copy(phase = YoutubePhase.UPLOADING, noSession = false, loadFailed = false)
        }
        viewModelScope.launch { upload(body) }
        return true
    }

    /** The Netscape text of the jar when it holds a signed-in session, else null. */
    private fun signedInCookies(): String? {
        val sources = session.cookieSources()
        val signedIn = sources.any {
            it.domain == YOUTUBE_DOMAIN && NetscapeCookies.hasSession(it.cookieHeader)
        }
        if (!signedIn) return null
        return NetscapeCookies.serialize(sources, clock.instant())
    }

    /** The WebView went away (rotation, back, destroyed): its jar must not outlive it. */
    fun webViewReleased() {
        session.clear()
    }

    /** The screen is gone for good: a half-done login must not stay on the phone. */
    public override fun onCleared() {
        poller?.cancel()
        if (mutableState.value.phase == YoutubePhase.SIGNING_IN) session.clear()
    }

    private suspend fun upload(body: String) {
        when (val result = api.setYoutubeCookies(body)) {
            is TunesResult.Success -> mutableState.update {
                it.copy(
                    status = YoutubeStatus.Ready(result.value),
                    phase = YoutubePhase.DONE,
                    failure = null
                )
            }

            is TunesResult.Failure -> fail(result.toFailure())
        }
    }

    /** "Sign out": the server forgets the session. */
    fun remove() {
        if (mutableState.value.status !is YoutubeStatus.Ready ||
            mutableState.value.phase.isBusy()
        ) {
            return
        }
        mutableState.update { it.copy(phase = YoutubePhase.UPLOADING, failure = null) }
        viewModelScope.launch {
            when (val result = api.clearYoutubeCookies()) {
                is TunesResult.Success -> mutableState.update {
                    it.copy(status = YoutubeStatus.Ready(result.value), phase = YoutubePhase.IDLE)
                }

                is TunesResult.Failure -> fail(result.toFailure())
            }
        }
    }

    private fun fail(failure: YoutubeFailure) {
        mutableState.update { it.copy(phase = YoutubePhase.FAILED, failure = failure) }
    }

    private fun YoutubePhase.isBusy() = this != YoutubePhase.IDLE && this != YoutubePhase.DONE &&
        this != YoutubePhase.FAILED

    private fun TunesResult.Failure.toStatusFailure(): YoutubeStatus =
        if (isForbidden()) YoutubeStatus.NotAdmin else YoutubeStatus.Failed(toLoadError())

    private fun TunesResult.Failure.isForbidden() =
        this is TunesResult.ApiError && error.kind == ErrorKind.FORBIDDEN

    private fun TunesResult.Failure.toFailure(): YoutubeFailure = when (this) {
        is TunesResult.NetworkError -> YoutubeFailure.NETWORK

        is TunesResult.Unauthorized -> YoutubeFailure.UNAUTHORIZED

        TunesResult.NotConfigured -> YoutubeFailure.UNAUTHORIZED

        is TunesResult.ProtocolError -> YoutubeFailure.SERVER

        is TunesResult.ApiError -> when (error.kind) {
            ErrorKind.FORBIDDEN -> YoutubeFailure.NOT_ADMIN
            ErrorKind.FEATURE_DISABLED -> YoutubeFailure.FEATURE_DISABLED
            ErrorKind.INVALID_PARAMETER, ErrorKind.MISSING_PARAMETER -> YoutubeFailure.REJECTED
            ErrorKind.PAYLOAD_TOO_LARGE -> YoutubeFailure.TOO_LARGE
            ErrorKind.RATE_LIMITED -> YoutubeFailure.RATE_LIMITED
            else -> YoutubeFailure.SERVER
        }
    }
}
