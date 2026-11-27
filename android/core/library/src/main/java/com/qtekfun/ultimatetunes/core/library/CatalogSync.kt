// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.library

import com.qtekfun.ultimatetunes.core.api.TunesResult
import java.time.Instant

/** Why a sync failed. The stored catalog is as it was. */
sealed interface CatalogSyncError {
    /** The server could not be asked, or refused. */
    data class Server(val failure: TunesResult.Failure) : CatalogSyncError

    /** The phone could not store what was read (full disk, inconsistent listing). */
    data object Storage : CatalogSyncError
}

/** How one sync ended. */
sealed interface CatalogSyncResult {
    /** The catalog now matches the server. */
    data object Synced : CatalogSyncResult

    /** Synced recently enough: nothing was read but who is connected. */
    data object Fresh : CatalogSyncResult

    /** The connection changed or the catalog was cleared meanwhile: nothing was stored. */
    data object Discarded : CatalogSyncResult

    data class Failed(val error: CatalogSyncError) : CatalogSyncResult
}

/** What the screens show about the sync. */
data class CatalogSyncState(
    val syncing: Boolean = false,
    /** The last full sync of this catalog; null when it never had one (it may be empty). */
    val lastSuccess: Instant? = null,
    /** Why the last attempt failed; null after one that worked. */
    val error: CatalogSyncError? = null
)

/** Keeps the local catalog in step with the server. */
interface CatalogSync {
    /**
     * For app start and connecting: makes sure the catalog belongs to who is connected (another
     * user or library clears it), then syncs unless the last sync is recent.
     */
    suspend fun syncIfStale(): CatalogSyncResult

    /** Syncs now (pull to refresh, "Sync now"). */
    suspend fun sync(): CatalogSyncResult

    /** Forgets the catalog and the pending changes (the connection was dropped). */
    suspend fun clear()
}
