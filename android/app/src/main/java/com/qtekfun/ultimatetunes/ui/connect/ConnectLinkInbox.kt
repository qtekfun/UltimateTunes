// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.connect

import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Hands a connect link from the activity's intent to [ConnectLinkViewModel], in memory only: the
 * activity drops it from the intent as soon as it is read, and the view model takes it from here
 * at once, so the key is never kept in a `Bundle`, on disk or in a log.
 */
@Singleton
class ConnectLinkInbox @Inject constructor() {
    private val link = MutableStateFlow<String?>(null)

    /** The link waiting to be confirmed, if any. */
    val pending: StateFlow<String?> = link.asStateFlow()

    /** A link just opened; it replaces one not taken yet. */
    fun offer(value: String) {
        link.value = value
    }

    /** Takes the waiting link (null if none) and forgets it. */
    fun take(): String? = link.getAndSet(null)

    private fun <T> MutableStateFlow<T>.getAndSet(value: T): T {
        while (true) {
            val current = this.value
            if (compareAndSet(current, value)) return current
        }
    }
}
