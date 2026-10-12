// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.imports

import android.content.ContentResolver
import android.net.Uri
import android.provider.OpenableColumns
import java.io.ByteArrayOutputStream
import java.io.IOException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/** The MIME types the file picker offers (CSV under its several names, and JSON). */
val IMPORT_MIME_TYPES = arrayOf(
    "text/csv",
    "text/comma-separated-values",
    "text/plain",
    "application/csv",
    "application/json",
    "application/vnd.ms-excel"
)

/**
 * Reads a document chosen with the system picker (Storage Access Framework): its display name and
 * at most [ImportViewModel.MAX_FILE_BYTES] + 1 bytes, so an oversized file is detected without
 * reading it all. Null when it cannot be read.
 */
suspend fun readPickedFile(resolver: ContentResolver, uri: Uri): PickedFile? =
    withContext(Dispatchers.IO) {
        try {
            val name = resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)
                ?.use { cursor -> if (cursor.moveToFirst()) cursor.getString(0) else null }
                ?: uri.lastPathSegment
                ?: DEFAULT_NAME
            val content = resolver.openInputStream(uri)?.use { input ->
                val out = ByteArrayOutputStream()
                val buffer = ByteArray(BUFFER_BYTES)
                val limit = ImportViewModel.MAX_FILE_BYTES + 1
                while (out.size() < limit) {
                    val read = input.read(buffer, 0, minOf(buffer.size, limit - out.size()))
                    if (read < 0) break
                    out.write(buffer, 0, read)
                }
                out.toByteArray()
            }
            content?.let { PickedFile(name, it) }
        } catch (_: IOException) {
            null
        } catch (_: SecurityException) {
            null
        }
    }

private const val DEFAULT_NAME = "playlist"
private const val BUFFER_BYTES = 8 * 1024
