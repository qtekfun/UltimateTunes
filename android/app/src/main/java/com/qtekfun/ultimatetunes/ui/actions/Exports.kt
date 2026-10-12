// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.actions

import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.core.net.toUri
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.player.PlayableTrack
import com.qtekfun.ultimatetunes.core.player.export.ExportManager
import com.qtekfun.ultimatetunes.core.player.export.ExportStatus
import com.qtekfun.ultimatetunes.ui.settings.AppPrefsStore
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.map

/**
 * Export to the phone (RF-14) as the screens use it: the folder the user picked (only while the
 * app still has access to it) and the export itself. [SafExports] is the real one.
 */
interface Exports {
    val status: StateFlow<ExportStatus>

    /** The export folder, or null when none was picked or its access was withdrawn. */
    val folder: Flow<String?>

    /** Keeps [uri], a folder just picked with the system picker, for this and later exports. */
    suspend fun setFolder(uri: String)

    /** Starts an export; false while another one runs (nothing starts then). */
    suspend fun start(
        folder: String,
        tracks: List<PlayableTrack>,
        aliases: Map<SongId, SongId>
    ): Boolean

    /** The report was shown. */
    fun dismiss()
}

/** [Exports] through the Storage Access Framework (no storage permission) and [ExportManager]. */
class SafExports @Inject constructor(
    @param:ApplicationContext private val context: Context,
    private val manager: ExportManager,
    private val prefs: AppPrefsStore
) : Exports {
    override val status: StateFlow<ExportStatus> get() = manager.status

    override val folder: Flow<String?> = prefs.exportFolder.map { it?.takeIf(::hasAccess) }

    override suspend fun setFolder(uri: String) {
        val resolver = context.contentResolver
        val flags = Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION
        try {
            resolver.takePersistableUriPermission(uri.toUri(), flags)
        } catch (ignored: SecurityException) {
            // Not a grant this app can keep: nothing changes.
            return
        }
        // Only one folder is kept: the previous grant is given back.
        resolver.persistedUriPermissions
            .filter { it.uri.toString() != uri }
            .forEach { resolver.releasePersistableUriPermission(it.uri, flags) }
        prefs.setExportFolder(uri)
    }

    override suspend fun start(
        folder: String,
        tracks: List<PlayableTrack>,
        aliases: Map<SongId, SongId>
    ): Boolean = manager.start(folder.toUri(), tracks, aliases)

    override fun dismiss() = manager.dismiss()

    private fun hasAccess(uri: String): Boolean = context.contentResolver.persistedUriPermissions
        .any { it.uri.toString() == uri && it.isWritePermission }
}
