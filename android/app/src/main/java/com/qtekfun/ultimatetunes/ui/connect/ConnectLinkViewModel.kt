// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.connect

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.model.ApiKeySecret
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import okhttp3.HttpUrl

/** What the connect-link dialog shows; nothing when [ConnectLinkUiState.Idle]. */
sealed interface ConnectLinkUiState {
    /** True when another link came while this one was showing, and was dropped. */
    val anotherLinkIgnored: Boolean

    data object Idle : ConnectLinkUiState {
        override val anotherLinkIgnored: Boolean = false
    }

    /** A link that cannot be used, and why; nothing was changed. */
    data class Refused(
        val error: ConnectLinkError,
        override val anotherLinkIgnored: Boolean = false
    ) : ConnectLinkUiState

    /**
     * A well-formed link waiting for the user: "Connect to [host]?" with the full [serverUrl].
     * [replacing] when the app is already connected (the current server stays until the new one
     * works). [armed] once the dialog has stayed unchanged for [ConnectLinkViewModel.ARM_DELAY_MS]
     * (on show, and again after the "another link was ignored" notice appears): until then Connect
     * does nothing, so a tap meant for something else cannot confirm it.
     * [checking] while the server is asked; [error] when it said no.
     */
    data class Confirm(
        val serverUrl: String,
        val host: String,
        val replacing: Boolean,
        val armed: Boolean = false,
        val checking: Boolean = false,
        val error: ConnectError? = null,
        override val anotherLinkIgnored: Boolean = false
    ) : ConnectLinkUiState {
        val canConfirm: Boolean get() = armed && !checking
    }
}

/**
 * Connect links (`ultimatetunes://connect?url=…&key=…`, the admin panel's QR code read by the
 * phone's camera app): parses each link from [ConnectLinkInbox] strictly ([ConnectLink]), always
 * asks for confirmation, and only then runs the same checks as the Connect screen
 * ([ConnectChecker]). Cancelling discards the link; the key lives only in this view model's
 * memory meanwhile.
 *
 * Against a hostile app firing links: while a dialog is showing, further links are dropped (the
 * dialog says so) instead of replacing it, and Connect only works [ARM_DELAY_MS] after a link is
 * shown. Links are taken only while the screen is started ([receiveLinks]), so one opened in the
 * background waits for the app to be visible.
 */
@HiltViewModel
class ConnectLinkViewModel @Inject constructor(
    api: TunesApi,
    private val gate: ConnectionGate,
    private val cleartext: CleartextPolicy,
    private val inbox: ConnectLinkInbox
) : ViewModel() {
    private val checker = ConnectChecker(api, gate)
    private val mutableState = MutableStateFlow<ConnectLinkUiState>(ConnectLinkUiState.Idle)
    val state: StateFlow<ConnectLinkUiState> = mutableState.asStateFlow()

    private var pending: Pending? = null
    private var arming: Job? = null

    private class Pending(val url: HttpUrl, val key: ApiKeySecret) {
        override fun toString(): String = "Pending(url=$url, key=redacted)"
    }

    /**
     * Takes links from the inbox until cancelled; the dialog's route runs it only while the
     * screen is at least started (`repeatOnLifecycle`).
     */
    suspend fun receiveLinks() {
        inbox.pending.filterNotNull().collect { inbox.take()?.let(::receive) }
    }

    private fun receive(link: String) {
        when (val shown = mutableState.value) {
            is ConnectLinkUiState.Refused ->
                mutableState.value = shown.copy(anotherLinkIgnored = true)

            is ConnectLinkUiState.Confirm -> {
                // The notice moves the buttons: Connect waits again, so no tap lands on it.
                mutableState.value = shown.copy(anotherLinkIgnored = true, armed = false)
                pending?.let(::arm)
            }

            ConnectLinkUiState.Idle -> show(ConnectLink.parse(link, cleartext))
        }
    }

    private fun show(parsed: ConnectLinkParse) {
        when (parsed) {
            is ConnectLinkParse.Invalid -> {
                pending = null
                mutableState.value = ConnectLinkUiState.Refused(parsed.error)
            }

            is ConnectLinkParse.Valid -> {
                val link = Pending(parsed.url, parsed.key)
                pending = link
                mutableState.value = ConnectLinkUiState.Confirm(
                    serverUrl = parsed.url.toString(),
                    host = parsed.url.host,
                    replacing = !gate.needsConnectNow
                )
                arm(link)
            }
        }
    }

    /** Enables Connect for [link] once its dialog has stayed the same for [ARM_DELAY_MS]. */
    private fun arm(link: Pending) {
        arming?.cancel()
        arming = viewModelScope.launch {
            delay(ARM_DELAY_MS)
            if (pending === link) {
                mutableState.update {
                    (it as? ConnectLinkUiState.Confirm)?.copy(armed = true) ?: it
                }
            }
        }
    }

    /** Runs the checks; the dialog closes once connected, or shows why not. */
    fun confirm() {
        val link = pending
        val shown = (mutableState.value as? ConnectLinkUiState.Confirm)?.takeIf { it.canConfirm }
        if (link == null || shown == null) return
        mutableState.value = shown.copy(checking = true, error = null)
        viewModelScope.launch {
            when (val result = checker.check(link.url, link.key)) {
                is ConnectCheck.Connected -> close()

                is ConnectCheck.Failed -> mutableState.update {
                    (it as? ConnectLinkUiState.Confirm)?.copy(
                        checking = false,
                        error = result.error
                    )
                        ?: it
                }
            }
        }
    }

    /** Cancel, or close after a refusal: the link is forgotten and nothing changes. */
    fun dismiss() {
        if ((mutableState.value as? ConnectLinkUiState.Confirm)?.checking == true) return
        close()
    }

    private fun close() {
        pending = null
        mutableState.value = ConnectLinkUiState.Idle
    }

    companion object {
        /** How long a newly shown link must be on screen before Connect works. */
        const val ARM_DELAY_MS = 1_000L
    }
}
