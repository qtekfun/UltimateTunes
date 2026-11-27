// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.library

import com.qtekfun.ultimatetunes.core.api.ServerConfig
import com.qtekfun.ultimatetunes.core.api.ServerConfigSource
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.library.db.CatalogDatabase
import com.qtekfun.ultimatetunes.core.library.db.MetaEntity
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
    pageSize: Int = PAGE_SIZE
) : CatalogSync {
    private val dao = database.sync()
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

    override suspend fun clear() {
        writing.withLock {
            generation++
            dao.clearAll()
        }
        state.update { it.copy(error = null) }
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
    private inner class Attempt(private val config: ServerConfig, private val startedIn: Int) {
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
            var meta = dao.meta()
            if (meta?.ownerId != owner) {
                write { dao.startOver(owner) }
                meta = null
            }
            if (onlyIfStale && isFresh(meta?.lastSyncAt)) return CatalogSyncResult.Fresh

            state.update { it.copy(syncing = true) }
            val snapshot = reader.read()
            write {
                dao.replace(snapshot, MetaEntity(ownerId = owner, lastSyncAt = clock.millis()))
            }
            return CatalogSyncResult.Synced
        }

        private suspend fun write(block: suspend () -> Unit) {
            writing.withLock {
                if (!current()) throw SyncStopped(CatalogSyncResult.Discarded)
                block()
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
