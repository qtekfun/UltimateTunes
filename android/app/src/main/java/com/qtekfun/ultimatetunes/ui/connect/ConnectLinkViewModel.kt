// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.connect

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.model.ApiKeySecret
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import okhttp3.HttpUrl

/** What the connect-link dialog shows; nothing when [ConnectLinkUiState.Idle]. */
sealed interface ConnectLinkUiState {
    data object Idle : ConnectLinkUiState

    /** A link that cannot be used, and why; nothing was changed. */
    data class Refused(val error: ConnectLinkError) : ConnectLinkUiState

    /**
     * A well-formed link waiting for the user: "Connect to [host]?" with the full [serverUrl].
     * [replacing] when the app is already connected (the current server stays until the new one
     * works). [checking] while the server is asked; [error] when it said no.
     */
    data class Confirm(
        val serverUrl: String,
        val host: String,
        val replacing: Boolean,
        val checking: Boolean = false,
        val error: ConnectError? = null
    ) : ConnectLinkUiState
}

/**
 * Connect links (`ultimatetunes://connect?url=…&key=…`, the admin panel's QR code read by the
 * phone's camera app): parses the link from [ConnectLinkInbox] strictly ([ConnectLink]), always
 * asks for confirmation, and only then runs the same checks as the Connect screen
 * ([ConnectChecker]). Cancelling discards the link; the key lives only in this view model's
 * memory meanwhile.
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

    private class Pending(val url: HttpUrl, val key: ApiKeySecret) {
        override fun toString(): String = "Pending(url=$url, key=redacted)"
    }

    init {
        viewModelScope.launch {
            inbox.pending.filterNotNull().collect { inbox.take()?.let(::receive) }
        }
    }

    private fun receive(link: String) {
        if ((mutableState.value as? ConnectLinkUiState.Confirm)?.checking == true) return
        when (val parsed = ConnectLink.parse(link, cleartext)) {
            is ConnectLinkParse.Invalid -> {
                pending = null
                mutableState.value = ConnectLinkUiState.Refused(parsed.error)
            }

            is ConnectLinkParse.Valid -> {
                pending = Pending(parsed.url, parsed.key)
                mutableState.value = ConnectLinkUiState.Confirm(
                    serverUrl = parsed.url.toString(),
                    host = parsed.url.host,
                    replacing = !gate.needsConnectNow
                )
            }
        }
    }

    /** Runs the checks; the dialog closes once connected, or shows why not. */
    fun confirm() {
        val link = pending
        val shown = (mutableState.value as? ConnectLinkUiState.Confirm)?.takeUnless { it.checking }
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
}
