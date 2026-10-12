// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

@file:OptIn(UnstableApi::class)

package com.qtekfun.ultimatetunes.core.player.offline

import android.app.Notification
import androidx.annotation.OptIn
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.offline.Download
import androidx.media3.exoplayer.offline.DownloadManager
import androidx.media3.exoplayer.offline.DownloadNotificationHelper
import androidx.media3.exoplayer.offline.DownloadService
import androidx.media3.exoplayer.scheduler.PlatformScheduler
import androidx.media3.exoplayer.scheduler.Scheduler
import com.qtekfun.ultimatetunes.core.player.R
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject

/**
 * Keeps the process alive while offline downloads run and shows their progress (RF-12, RF-13).
 * When the network requirement is not met, the platform scheduler restarts it later.
 */
@AndroidEntryPoint
class OfflineDownloadService :
    DownloadService(
        NOTIFICATION_ID,
        DEFAULT_FOREGROUND_NOTIFICATION_UPDATE_INTERVAL,
        CHANNEL_ID,
        R.string.player_downloads_channel,
        R.string.player_downloads_channel_description
    ) {
    @Inject
    lateinit var downloads: OfflineDownloads

    private val notifications by lazy { DownloadNotificationHelper(this, CHANNEL_ID) }

    override fun getDownloadManager(): DownloadManager = downloads.manager

    override fun getScheduler(): Scheduler = PlatformScheduler(this, SCHEDULER_JOB_ID)

    override fun getForegroundNotification(
        downloads: List<Download>,
        notMetRequirements: Int
    ): Notification = notifications.buildProgressNotification(
        this,
        R.drawable.player_ic_download,
        null,
        null,
        downloads,
        notMetRequirements
    )

    private companion object {
        const val NOTIFICATION_ID = 0x5554
        const val CHANNEL_ID = "downloads"

        /** Job id of Media3's scheduler; the offline sync uses [OfflineSyncScheduler]'s ids. */
        const val SCHEDULER_JOB_ID = 0x5501
    }
}
