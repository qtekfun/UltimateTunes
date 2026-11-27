// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.library

import com.qtekfun.ultimatetunes.core.library.CatalogSync
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.channels.consumeEach
import kotlinx.coroutines.launch

/** Asks for the catalog to catch up after a change made in the app, without waiting for it. */
fun interface CatalogRefresh {
    fun request()
}

/**
 * Syncs for the requests, one sync at a time: those arriving while one runs share the next one,
 * which therefore sees every change made before it started.
 */
@Singleton
class CoalescedCatalogRefresh internal constructor(sync: CatalogSync, scope: CoroutineScope) :
    CatalogRefresh {
    @Inject
    constructor(sync: CatalogSync) :
        this(sync, CoroutineScope(SupervisorJob() + Dispatchers.Default))

    private val requests = Channel<Unit>(Channel.CONFLATED)

    init {
        scope.launch {
            requests.consumeEach { sync.sync() }
        }
    }

    override fun request() {
        requests.trySend(Unit)
    }
}
