// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.library

import androidx.room3.withWriteTransaction
import com.qtekfun.ultimatetunes.core.api.ServerConfig
import com.qtekfun.ultimatetunes.core.api.ServerConfigSource
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.library.db.CatalogDatabase
import com.qtekfun.ultimatetunes.core.library.db.MetaEntity
import com.qtekfun.ultimatetunes.core.library.pending.nextGroup
import java.time.Clock
import java.time.Duration
import java.time.Instant
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

/** What a sync is doing, apart from what the database remembers. */
internal data class SyncActivity(val syncing: Boolean = false, val error: CatalogSyncError? = null)

/**
 * Reads the whole library, the playlists and the favourites, and only then replaces the catalog,
 * in one transaction: a page or a call that fails leaves what was stored. One sync runs at a time.
 */
internal class CatalogSyncer(
    private val api: TunesApi,
    database: CatalogDatabase,
    private val configSource: ServerConfigSource,
    private val clock: Clock,
    private val minInterval: Duration = MIN_INTERVAL,
    pageSize: Int = PAGE_SIZE,
    /** True while nothing may be sent (offline mode): the queue waits. */
    private val holdChanges: suspend () -> Boolean = { false }
) : CatalogSync {
    private val db = database
    private val dao = database.sync()
    val queue = database.queue()
    private val local = LocalApply(queue)
    private val reader = CatalogReader(api, dao, pageSize)
    private val running = Mutex()

    /** Held while writing, so [clear] never lands in the middle of a sync's writes. */
    private val writing = Mutex()

    /** Counts the clears: a sync started before the last one stores nothing. */
    @Volatile
    private var generation = 0

    private val state = MutableStateFlow(SyncActivity())
    val activity: StateFlow<SyncActivity> = state

    override suspend fun syncIfStale(): CatalogSyncResult = inBackground(onlyIfStale = true)

    override suspend fun sync(): CatalogSyncResult = inBackground(onlyIfStale = false)

    /** One transaction, never in the middle of a sync's writes or a [clear]. */
    suspend fun write(block: suspend () -> Unit) {
        writing.withLock { db.withWriteTransaction { block() } }
    }

    /** [write] if the catalog is the current connection's; false when it is not. */
    suspend fun writeIfOwned(block: suspend () -> Unit): Boolean = writing.withLock {
        val config = configSource.config.value
        val mine = config != null && dao.meta()?.verifiedFor == fingerprintOf(config)
        if (mine) db.withWriteTransaction { block() }
        mine
    }

    /** Sends the queued changes of the current connection; one at a time with the syncs. */
    suspend fun send(): SendResult = withContext(Dispatchers.Default) {
        running.withLock {
            val config = configSource.config.value
            val result = try {
                config?.let { Attempt(it, generation).send() }
            } catch (e: CancellationException) {
                throw e
            } catch (
                // The connection changed, or the storage failed: the queue stays.
                @Suppress("TooGenericExceptionCaught", "SwallowedException") e: Exception
            ) {
                null
            }
            result ?: SendResult(waiting = stillWaiting())
        }
    }

    /** True if changes wait; also when the queue cannot be read, to try again. */
    @Suppress("TooGenericExceptionCaught", "SwallowedException") // Any storage failure.
    private suspend fun stillWaiting(): Boolean = try {
        nextGroup(queue.all(), emptySet()).isNotEmpty()
    } catch (e: CancellationException) {
        throw e
    } catch (e: Exception) {
        true
    }

    override suspend fun clear() {
        writing.withLock {
            generation++
            try {
                dao.clearAll()
            } catch (e: CancellationException) {
                throw e
            } catch (
                // A full or damaged disk must not crash a disconnect. What stays is not shown to
                // any other connection (see MetaEntity.verifiedFor), and the next owner clears it.
                @Suppress("TooGenericExceptionCaught", "SwallowedException") e: RuntimeException
            ) {
                state.update { it.copy(error = CatalogSyncError.Storage) }
                return@withLock
            }
            state.update { it.copy(error = null) }
        }
    }

    /** Off the caller's thread: a large library takes a while to decode and sort out. */
    private suspend fun inBackground(onlyIfStale: Boolean): CatalogSyncResult =
        withContext(Dispatchers.Default) { oneAtATime(onlyIfStale) }

    private suspend fun oneAtATime(onlyIfStale: Boolean): CatalogSyncResult = running.withLock {
        val config = configSource.config.value
            ?: return@withLock CatalogSyncResult.Failed(
                CatalogSyncError.Server(TunesResult.NotConfigured)
            )
        val attempt = Attempt(config, generation)
        try {
            attempt.guarded { attempt.sync(onlyIfStale) }.also { result ->
                val worked = result == CatalogSyncResult.Synced || result == CatalogSyncResult.Fresh
                if (worked) state.update { it.copy(error = null) }
            }
        } finally {
            state.update { it.copy(syncing = false) }
        }
    }

    /** One sync of the server of [config], valid while no clear and no other server came. */
    private inner class Attempt(private val config: ServerConfig, private val startedIn: Int) :
        SendSession {
        @Volatile
        private var moved = false

        /** Runs [block], noting a change of connection, and turns every failure into a result. */
        suspend fun guarded(block: suspend () -> CatalogSyncResult): CatalogSyncResult = try {
            coroutineScope {
                val watcher = launch(start = CoroutineStart.UNDISPATCHED) {
                    configSource.config.first { it != config }
                    moved = true
                }
                block().also { watcher.cancel() }
            }
        } catch (e: SyncStopped) {
            report(e.result)
        } catch (e: CancellationException) {
            throw e
        } catch (
            // SQLite failures are RuntimeExceptions of a different class on each driver.
            @Suppress("TooGenericExceptionCaught", "SwallowedException") e: RuntimeException
        ) {
            report(CatalogSyncResult.Failed(CatalogSyncError.Storage))
        }

        /** [result], remembering why it failed unless the connection changed meanwhile. */
        private fun report(result: CatalogSyncResult): CatalogSyncResult = when {
            result !is CatalogSyncResult.Failed -> result

            // A failure caused by disconnecting is not news.
            !current() -> CatalogSyncResult.Discarded

            else -> result.also { failed -> state.update { it.copy(error = failed.error) } }
        }

        private fun current(): Boolean = startedIn == generation &&
            !moved &&
            configSource.config.value == config

        suspend fun sync(onlyIfStale: Boolean): CatalogSyncResult {
            // User ids are unique to one server's library, whatever address reaches it.
            val owner = api.me().orStop().id.value
            val connection = fingerprintOf(config)
            var meta = dao.meta()
            if (meta?.ownerId != owner) {
                write { dao.startOver(owner, connection) }
                meta = null
            } else if (meta.verifiedFor != connection) {
                // The same user over a new address or key: its catalog shows again.
                val verified = meta.copy(verifiedFor = connection)
                write { dao.putMeta(verified) }
                meta = verified
            }
            // What waits goes first, so that what is read next already has it.
            val sent = send()?.changed == true
            if (onlyIfStale && !sent && isFresh(meta?.lastSyncAt)) return CatalogSyncResult.Fresh

            state.update { it.copy(syncing = true) }
            val snapshot = reader.read()
            write {
                val done = MetaEntity(
                    ownerId = owner,
                    lastSyncAt = clock.millis(),
                    verifiedFor = connection
                )
                db.withWriteTransaction {
                    dao.replace(snapshot, done)
                    // What was not sent still shows.
                    queue.all().forEach { local.apply(it) }
                }
            }
            return CatalogSyncResult.Synced
        }

        /** Null when the catalog is not this connection's. */
        suspend fun send(): SendResult? {
            if (holdChanges() || dao.meta()?.verifiedFor != fingerprintOf(config)) return null
            return PendingSender(api, queue, this).run()
        }

        override fun check() {
            if (!current()) throw SyncStopped(CatalogSyncResult.Discarded)
        }

        override suspend fun write(block: suspend () -> Unit) {
            writing.withLock {
                check()
                db.withWriteTransaction { block() }
            }
        }

        private fun isFresh(lastSyncAt: Long?): Boolean {
            if (lastSyncAt == null) return false
            val age = Duration.between(Instant.ofEpochMilli(lastSyncAt), clock.instant())
            // A negative age means the clock went back: sync rather than wait for it.
            return !age.isNegative && age < minInterval
        }
    }

    companion object {
        /** How old a sync may be before starting the app or connecting syncs again. */
        val MIN_INTERVAL: Duration = Duration.ofMinutes(15)

        /** The most `search3` returns for one page. */
        const val PAGE_SIZE = 500
    }
}
