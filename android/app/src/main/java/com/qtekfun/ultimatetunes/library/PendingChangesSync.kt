// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.library

import com.qtekfun.ultimatetunes.availability.PhoneAvailability
import com.qtekfun.ultimatetunes.core.library.OfflineChanges
import com.qtekfun.ultimatetunes.core.library.SendResult
import com.qtekfun.ultimatetunes.core.player.offline.CollectionKind
import com.qtekfun.ultimatetunes.playback.OfflineControls
import com.qtekfun.ultimatetunes.ui.connect.ConnectionGate
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.conflate
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch

/** Has the system try to send the waiting changes later, even with the app closed. */
fun interface SendLater {
    fun schedule()
}

/**
 * Sends the changes made on the phone (PLAN T35): at once while the server can be reached, again
 * when the connection comes back or offline mode ends, and through [SendLater] otherwise. After a
 * playlist kept offline reaches the server, its downloads are brought up to date.
 */
@Singleton
@Suppress("LongParameterList") // Collaborators are injected one by one.
class PendingChangesSync internal constructor(
    private val changes: OfflineChanges,
    private val phone: PhoneAvailability,
    private val gate: ConnectionGate,
    private val catalog: CatalogRefresh,
    private val offline: OfflineControls,
    private val later: SendLater,
    private val scope: CoroutineScope
) {
    @Inject
    constructor(
        changes: OfflineChanges,
        phone: PhoneAvailability,
        gate: ConnectionGate,
        catalog: CatalogRefresh,
        offline: OfflineControls,
        later: SendLater
    ) : this(
        changes,
        phone,
        gate,
        catalog,
        offline,
        later,
        CoroutineScope(SupervisorJob() + Dispatchers.Default)
    )

    fun start() {
        scope.launch { sendWhenPossible() }
        scope.launch { followKeptPlaylists() }
    }

    /** One round now (the background worker's too). */
    suspend fun send(): SendResult = changes.send().also { if (it.changed) catalog.request() }

    private suspend fun sendWhenPossible() {
        val waiting = changes.status.map { it.latest to it.count }.distinctUntilChanged()
        val reachable = combine(phone.availability, gate.needsConnect) { now, needsConnect ->
            !now.onlyPhone && !needsConnect
        }.distinctUntilChanged()
        combine(waiting, reachable) { (_, count), can -> count to can }
            .conflate()
            .collect { (count, can) ->
                if (count == 0) return@collect
                later.schedule()
                if (can) send()
            }
    }

    private suspend fun followKeptPlaylists() {
        var before = changes.status.first().playlists
        changes.status.map { it.playlists }.distinctUntilChanged().collect { now ->
            val sent = before - now
            before = now
            if (sent.isEmpty()) return@collect
            val selection = offline.selection.first()
            if (sent.any { selection.keepsCollection(CollectionKind.PLAYLIST, it.value) }) {
                offline.syncSoon()
            }
        }
    }
}
