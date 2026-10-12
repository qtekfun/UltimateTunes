// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.offline

import android.app.job.JobInfo
import android.app.job.JobParameters
import android.app.job.JobScheduler
import android.app.job.JobService
import android.content.ComponentName
import android.content.Context
import dagger.hilt.android.AndroidEntryPoint
import dagger.hilt.android.qualifiers.ApplicationContext
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/**
 * Schedules the offline sync (RF-12): once now when the selection changes, and periodically while
 * anything is kept, on any network or only unmetered ones per the Wi-Fi setting. Uses the
 * platform job scheduler (what WorkManager uses underneath on every supported API level).
 */
@Singleton
class OfflineSyncScheduler @Inject constructor(
    @param:ApplicationContext private val context: Context
) {
    private val jobs get() = context.getSystemService(JobScheduler::class.java)
    private val component get() = ComponentName(context, OfflineSyncJobService::class.java)

    /** Syncs as soon as the network allows, and every [PERIOD_HOURS] hours after. */
    fun schedule(wifiOnly: Boolean) {
        val network = if (wifiOnly) JobInfo.NETWORK_TYPE_UNMETERED else JobInfo.NETWORK_TYPE_ANY
        jobs.schedule(
            JobInfo.Builder(NOW_JOB_ID, component).setRequiredNetworkType(network).build()
        )
        jobs.schedule(
            JobInfo.Builder(PERIODIC_JOB_ID, component)
                .setRequiredNetworkType(network)
                .setPeriodic(TimeUnit.HOURS.toMillis(PERIOD_HOURS))
                .setPersisted(true)
                .build()
        )
    }

    /** Nothing is kept any more: no periodic sync. */
    fun cancel() {
        jobs.cancel(PERIODIC_JOB_ID)
    }

    companion object {
        const val PERIOD_HOURS = 12L
        const val NOW_JOB_ID = 0x5502
        const val PERIODIC_JOB_ID = 0x5503
    }
}

/** Runs one [OfflineSyncer.sync] and waits (bounded) for the downloads it started. */
@AndroidEntryPoint
class OfflineSyncJobService : JobService() {
    @Inject
    lateinit var syncer: OfflineSyncer

    @Inject
    lateinit var downloads: OfflineDownloads

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val running = mutableMapOf<Int, Job>()

    override fun onStartJob(params: JobParameters): Boolean {
        running[params.jobId] = scope.launch {
            syncer.sync()
            // Keep the process alive while downloads run, within the job's time budget.
            downloads.awaitIdle(MAX_WAIT_MS)
            running.remove(params.jobId)
            jobFinished(params, false)
        }
        return true
    }

    override fun onStopJob(params: JobParameters): Boolean {
        running.remove(params.jobId)?.cancel()
        // Retry later: the network went away or the system needs the resources.
        return true
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    private companion object {
        /** Below the ten minutes a job may run. */
        val MAX_WAIT_MS = TimeUnit.MINUTES.toMillis(9)
    }
}
