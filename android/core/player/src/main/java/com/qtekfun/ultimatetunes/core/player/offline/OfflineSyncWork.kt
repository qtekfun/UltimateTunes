// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.offline

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import dagger.hilt.EntryPoint
import dagger.hilt.InstallIn
import dagger.hilt.android.EntryPointAccessors
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Schedules the offline sync with WorkManager (RF-12): once now when the selection changes, and
 * periodically while anything is kept, on any network or only unmetered ones per the Wi-Fi
 * setting.
 */
@Singleton
class OfflineSyncScheduler @Inject constructor(
    @param:ApplicationContext private val context: Context
) {
    private val work get() = WorkManager.getInstance(context)

    /** Syncs as soon as the network allows, and every [PERIOD_HOURS] hours after. */
    fun schedule(wifiOnly: Boolean) {
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(if (wifiOnly) NetworkType.UNMETERED else NetworkType.CONNECTED)
            .build()
        work.enqueueUniqueWork(
            NOW_WORK,
            ExistingWorkPolicy.REPLACE,
            OneTimeWorkRequestBuilder<OfflineSyncWorker>().setConstraints(constraints).build()
        )
        work.enqueueUniquePeriodicWork(
            PERIODIC_WORK,
            ExistingPeriodicWorkPolicy.UPDATE,
            PeriodicWorkRequestBuilder<OfflineSyncWorker>(PERIOD_HOURS, TimeUnit.HOURS)
                .setConstraints(constraints)
                .build()
        )
    }

    /** Nothing is kept any more: no periodic sync. */
    fun cancel() {
        work.cancelUniqueWork(PERIODIC_WORK)
    }

    companion object {
        const val PERIOD_HOURS = 12L
        const val NOW_WORK = "offline-sync-now"
        const val PERIODIC_WORK = "offline-sync-periodic"
    }
}

/** Runs one [OfflineSyncer.sync] and waits (bounded) for the downloads it started. */
class OfflineSyncWorker(context: Context, params: WorkerParameters) :
    CoroutineWorker(context, params) {
    /** The worker is built by WorkManager's default factory, so it reaches Hilt this way. */
    @EntryPoint
    @InstallIn(SingletonComponent::class)
    interface Dependencies {
        fun syncer(): OfflineSyncer

        fun downloads(): OfflineDownloads
    }

    override suspend fun doWork(): Result {
        val deps = EntryPointAccessors.fromApplication(applicationContext, Dependencies::class.java)
        deps.syncer().sync()
        // Keep the process alive while downloads run, within a worker's time budget.
        deps.downloads().awaitIdle(MAX_WAIT_MS)
        return Result.success()
    }

    private companion object {
        /** Below the ten minutes a worker may run. */
        val MAX_WAIT_MS = TimeUnit.MINUTES.toMillis(9)
    }
}
