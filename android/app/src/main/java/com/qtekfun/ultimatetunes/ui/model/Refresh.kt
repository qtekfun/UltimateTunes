// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.model

import com.qtekfun.ultimatetunes.core.library.CatalogSync
import com.qtekfun.ultimatetunes.core.library.CatalogSyncError
import com.qtekfun.ultimatetunes.core.library.CatalogSyncResult
import com.qtekfun.ultimatetunes.core.library.CatalogSyncState
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** A pull to refresh under way, or why the last one failed (shown once). */
data class RefreshState(val refreshing: Boolean = false, val error: LoadError? = null)

/**
 * The pull to refresh of one screen: runs [block], which answers why it failed or null. What the
 * screen shows is not touched, so a failure keeps it.
 */
class Refresher(private val scope: CoroutineScope, private val block: suspend () -> LoadError?) {
    private val mutableState = MutableStateFlow(RefreshState())
    val state: StateFlow<RefreshState> = mutableState.asStateFlow()

    fun refresh() {
        if (mutableState.value.refreshing) return
        mutableState.value = RefreshState(refreshing = true)
        scope.launch {
            val error = block()
            mutableState.value = RefreshState(error = error)
        }
    }

    fun messageShown() {
        mutableState.update { it.copy(error = null) }
    }
}

fun CatalogSyncError.toLoadError(): LoadError = when (this) {
    is CatalogSyncError.Server -> failure.toLoadError()
    CatalogSyncError.Storage -> LoadError.SERVER
}

/** Syncs the catalog now; why it failed, or null. */
suspend fun CatalogSync.syncError(): LoadError? =
    (sync() as? CatalogSyncResult.Failed)?.error?.toLoadError()

/**
 * What a screen of the catalog shows: [value] once the catalog has been read in full, the reason
 * while it never could be, else loading.
 */
fun <T> CatalogSyncState.contentState(value: () -> T): LoadState<T> {
    val failed = error
    return when {
        lastSuccess != null -> LoadState.Ready(value())
        failed != null -> LoadState.Failed(failed.toLoadError())
        else -> LoadState.Loading
    }
}
