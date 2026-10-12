// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.export

import android.Manifest
import android.app.Notification
import android.app.PendingIntent
import android.content.Context
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.os.Build
import androidx.core.app.NotificationChannelCompat
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.work.CoroutineWorker
import androidx.work.ForegroundInfo
import androidx.work.WorkerParameters
import com.qtekfun.ultimatetunes.core.player.R
import dagger.hilt.EntryPoint
import dagger.hilt.InstallIn
import dagger.hilt.android.EntryPointAccessors
import dagger.hilt.components.SingletonComponent
import java.io.File
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * Runs one export (RF-14) as foreground work with a progress notification, then posts a summary
 * (songs copied and skipped).
 */
class ExportWorker(context: Context, params: WorkerParameters) :
    CoroutineWorker(context, params) {
    /** The worker is built by WorkManager's default factory, so it reaches Hilt this way. */
    @EntryPoint
    @InstallIn(SingletonComponent::class)
    interface Dependencies {
        fun exports(): ExportManager
    }

    private val notifications = NotificationManagerCompat.from(applicationContext)

    override suspend fun doWork(): Result {
        val manager = EntryPointAccessors
            .fromApplication(applicationContext, Dependencies::class.java)
            .exports()
        createChannel()
        showProgress(0, 0)
        val report = inputData.getString(KEY_REQUEST)?.let { path ->
            withContext(Dispatchers.IO) { manager.run(File(path), ::showProgress) }
        }
        report?.let { notify(SUMMARY_ID, summary(it)) }
        return if (report == null) Result.failure() else Result.success()
    }

    override suspend fun getForegroundInfo(): ForegroundInfo = foregroundInfo(progress(0, 0))

    private fun foregroundInfo(notification: Notification): ForegroundInfo =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ForegroundInfo(PROGRESS_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } else {
            ForegroundInfo(PROGRESS_ID, notification)
        }

    /**
     * Runs in the foreground with the progress notification. Starting in the foreground can be
     * refused (the app went to the background): the export goes on as ordinary work.
     */
    private fun showProgress(done: Int, total: Int) {
        try {
            setForegroundAsync(foregroundInfo(progress(done, total)))
        } catch (ignored: IllegalStateException) {
            // Runs without the notification.
        }
    }

    private fun progress(done: Int, total: Int): Notification =
        NotificationCompat.Builder(applicationContext, CHANNEL_ID)
            .setSmallIcon(R.drawable.player_ic_export)
            .setContentTitle(applicationContext.getString(R.string.export_running))
            .setContentText(
                if (total > 0) {
                    applicationContext.getString(R.string.export_progress, done, total)
                } else {
                    null
                }
            )
            .setProgress(total, done, total == 0)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setSilent(true)
            .setContentIntent(openApp())
            .build()

    private fun summary(report: ExportReport): Notification =
        NotificationCompat.Builder(applicationContext, CHANNEL_ID)
            .setSmallIcon(R.drawable.player_ic_export)
            .setContentTitle(applicationContext.getString(R.string.export_done))
            .setContentText(
                applicationContext.resources.getQuantityString(
                    R.plurals.export_done_summary,
                    report.exported,
                    report.exported,
                    report.skipped.size
                )
            )
            .setAutoCancel(true)
            .setContentIntent(openApp())
            .build()

    private fun openApp(): PendingIntent? {
        val intent = applicationContext.packageManager
            .getLaunchIntentForPackage(applicationContext.packageName) ?: return null
        return PendingIntent.getActivity(
            applicationContext,
            0,
            intent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
    }

    private fun createChannel() {
        notifications.createNotificationChannel(
            NotificationChannelCompat.Builder(CHANNEL_ID, NotificationManagerCompat.IMPORTANCE_LOW)
                .setName(applicationContext.getString(R.string.export_channel))
                .setDescription(applicationContext.getString(R.string.export_channel_description))
                .build()
        )
    }

    /** Posts [notification] when the user allowed notifications (Android 13+ asks). */
    private fun notify(id: Int, notification: Notification) {
        val allowed = Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
            ContextCompat.checkSelfPermission(
                applicationContext,
                Manifest.permission.POST_NOTIFICATIONS
            ) == PackageManager.PERMISSION_GRANTED
        if (allowed) notifications.notify(id, notification)
    }

    companion object {
        /** Input: the absolute path of the request file ExportManager wrote. */
        const val KEY_REQUEST = "request"

        const val CHANNEL_ID = "export"
        private const val PROGRESS_ID = 0x5554_0001
        private const val SUMMARY_ID = 0x5554_0002
    }
}
