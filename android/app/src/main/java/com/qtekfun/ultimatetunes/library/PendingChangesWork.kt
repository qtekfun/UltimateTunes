// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.library

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.qtekfun.ultimatetunes.core.api.ServerConfigSource
import com.qtekfun.ultimatetunes.ui.settings.PlaybackSettingsStore
import dagger.hilt.EntryPoint
import dagger.hilt.InstallIn
import dagger.hilt.android.EntryPointAccessors
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.first

private const val WORK_NAME = "pending-changes"

/** [SendLater] with WorkManager: runs once there is a network, and retries with backoff. */
@Singleton
class WorkSendLater @Inject constructor(@param:ApplicationContext private val context: Context) :
    SendLater {
    override fun schedule() {
        val request = OneTimeWorkRequestBuilder<PendingChangesWorker>()
            .setConstraints(
                Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()
            )
            .build()
        WorkManager.getInstance(context)
            .enqueueUniqueWork(WORK_NAME, ExistingWorkPolicy.KEEP, request)
    }
}

/** Sends the waiting changes; retried while some are left. Offline mode sends nothing. */
class PendingChangesWorker(context: Context, params: WorkerParameters) :
    CoroutineWorker(context, params) {
    /** The worker is built by WorkManager's default factory, so it reaches Hilt this way. */
    @EntryPoint
    @InstallIn(SingletonComponent::class)
    interface Dependencies {
        fun sync(): PendingChangesSync

        fun config(): ServerConfigSource

        fun settings(): PlaybackSettingsStore
    }

    override suspend fun doWork(): Result {
        val deps = EntryPointAccessors.fromApplication(applicationContext, Dependencies::class.java)
        return when {
            deps.settings().settings.first().offlineOnly -> Result.success()

            // Started before the saved server was restored, or disconnected since.
            deps.config().config.value == null ->
                if (runAttemptCount < MAX_RETRIES) Result.retry() else Result.success()

            deps.sync().send().waiting -> Result.retry()

            else -> Result.success()
        }
    }

    private companion object {
        const val MAX_RETRIES = 5
    }
}
