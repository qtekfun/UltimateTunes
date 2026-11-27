// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.library

import com.qtekfun.ultimatetunes.core.library.CatalogSync
import com.qtekfun.ultimatetunes.core.library.CatalogSyncResult
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test

class CatalogRefreshTest {
    @Test
    fun `requests made while a sync runs share the next one`() {
        var syncs = 0
        var gate = CompletableDeferred<Unit>()
        val sync = object : CatalogSync {
            override suspend fun syncIfStale() = CatalogSyncResult.Fresh

            override suspend fun sync(): CatalogSyncResult {
                syncs++
                gate.await()
                return CatalogSyncResult.Synced
            }

            override suspend fun clear() = Unit
        }
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.Unconfined)
        val refresh = CoalescedCatalogRefresh(sync, scope)

        repeat(4) { refresh.request() }
        assertEquals(1, syncs)

        val first = gate
        gate = CompletableDeferred()
        first.complete(Unit)
        assertEquals(2, syncs)
        gate.complete(Unit)
        assertEquals(2, syncs)
        scope.cancel()
    }
}
