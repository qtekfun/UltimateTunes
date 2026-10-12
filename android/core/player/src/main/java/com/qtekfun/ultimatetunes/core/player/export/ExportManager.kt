// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.export

import android.content.Context
import android.net.Uri
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.workDataOf
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.player.PlayableTrack
import com.qtekfun.ultimatetunes.core.player.media.MediaCaches
import dagger.hilt.android.qualifiers.ApplicationContext
import java.io.File
import java.io.IOException
import java.util.UUID
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.serialization.Serializable
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json

/** An export as the app shows it. */
sealed interface ExportStatus {
    data object Idle : ExportStatus

    /** [done] of [total] songs handled. */
    data class Running(val done: Int, val total: Int) : ExportStatus

    data class Finished(val report: ExportReport) : ExportStatus
}

/** What one export copies, and where to; kept in a file because work data is small. */
@Serializable
internal data class ExportRequest(
    val tree: String,
    val tracks: List<PlayableTrack>,
    val aliases: Map<String, String> = emptyMap()
)

/**
 * Export to the phone (RF-14): copies songs fully on the phone to the folder the user picked, in
 * the background with a progress notification ([ExportWorker], WorkManager, one export at a time).
 * [status] follows the export while the app runs, ending with the list of skipped songs.
 */
@Singleton
class ExportManager @Inject constructor(
    @param:ApplicationContext private val context: Context,
    private val caches: MediaCaches
) {
    private val mutableStatus = MutableStateFlow<ExportStatus>(ExportStatus.Idle)
    val status: StateFlow<ExportStatus> = mutableStatus.asStateFlow()

    private val folder get() = File(context.noBackupFilesDir, "exports")

    /**
     * Exports [tracks] to [tree] (a folder granted with the system picker, its permission
     * persisted). [aliases] maps `yt:` ids to the library ids the server gave them.
     */
    fun start(tree: Uri, tracks: List<PlayableTrack>, aliases: Map<SongId, SongId> = emptyMap()) {
        if (tracks.isEmpty()) return
        val request = ExportRequest(
            tree = tree.toString(),
            tracks = tracks,
            aliases = aliases.entries.associate { it.key.value to it.value.value }
        )
        val file = File(folder.apply { mkdirs() }, "${UUID.randomUUID()}.json")
        file.writeText(JSON.encodeToString(request))
        mutableStatus.value = ExportStatus.Running(0, tracks.distinctBy { it.id }.size)
        WorkManager.getInstance(context).enqueueUniqueWork(
            WORK_NAME,
            ExistingWorkPolicy.APPEND_OR_REPLACE,
            OneTimeWorkRequestBuilder<ExportWorker>()
                .setInputData(workDataOf(ExportWorker.KEY_REQUEST to file.absolutePath))
                .build()
        )
    }

    /** The report was shown: back to idle. */
    fun dismiss() {
        if (mutableStatus.value is ExportStatus.Finished) mutableStatus.value = ExportStatus.Idle
    }

    /** Runs the export kept in [requestFile] (by the worker), then deletes that file. */
    internal fun run(
        requestFile: File,
        onProgress: (done: Int, total: Int) -> Unit
    ): ExportReport? {
        // Only requests this class wrote, in its own folder.
        if (requestFile.parentFile?.canonicalPath != folder.canonicalPath) return null
        val request = try {
            JSON.decodeFromString<ExportRequest>(requestFile.readText())
        } catch (ignored: IOException) {
            return null
        } catch (ignored: SerializationException) {
            requestFile.delete()
            return null
        }
        val exporter = Exporter(
            CacheExportSource(caches),
            DocumentTreeTarget(context.contentResolver, Uri.parse(request.tree))
        )
        val report = exporter.export(
            tracks = request.tracks,
            aliases = request.aliases.entries.associate { SongId(it.key) to SongId(it.value) }
        ) { done, total ->
            mutableStatus.value = ExportStatus.Running(done, total)
            onProgress(done, total)
        }
        requestFile.delete()
        mutableStatus.value = ExportStatus.Finished(report)
        return report
    }

    private companion object {
        const val WORK_NAME = "export"
        val JSON = Json { ignoreUnknownKeys = true }
    }
}
