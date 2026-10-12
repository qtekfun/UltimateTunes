// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.export

import android.content.ContentResolver
import android.net.Uri
import android.provider.DocumentsContract
import android.provider.DocumentsContract.Document
import android.webkit.MimeTypeMap
import java.io.IOException
import java.io.InputStream

/**
 * The folder the user picked with the system folder picker (Storage Access Framework, RF-14): no
 * storage permission, only the tree the user granted. Folders are created as needed and an
 * earlier export of the same file is replaced.
 */
class DocumentTreeTarget(private val resolver: ContentResolver, private val tree: Uri) :
    ExportTarget {
    private val folders = HashMap<List<String>, Uri>()

    override fun write(path: List<String>, content: InputStream) = guarded {
        var folder = DocumentsContract.buildDocumentUriUsingTree(
            tree,
            DocumentsContract.getTreeDocumentId(tree)
        )
        for (depth in 1 until path.size) {
            val parent = folder
            val name = path[depth - 1]
            folder = folders.getOrPut(path.subList(0, depth).toList()) {
                childOf(parent, name) ?: create(parent, Document.MIME_TYPE_DIR, name)
            }
        }
        val name = path.last()
        childOf(folder, name)?.let { DocumentsContract.deleteDocument(resolver, it) }
        val file = create(folder, mimeTypeOf(name), name)
        try {
            val out = resolver.openOutputStream(file, "w") ?: throw IOException("Not writable")
            out.use { content.copyTo(it) }
        } catch (failed: IOException) {
            DocumentsContract.deleteDocument(resolver, file)
            throw failed
        }
    }

    private fun childOf(folder: Uri, name: String): Uri? {
        val children = DocumentsContract.buildChildDocumentsUriUsingTree(
            tree,
            DocumentsContract.getDocumentId(folder)
        )
        val columns = arrayOf(Document.COLUMN_DOCUMENT_ID, Document.COLUMN_DISPLAY_NAME)
        resolver.query(children, columns, null, null, null)?.use { cursor ->
            while (cursor.moveToNext()) {
                if (cursor.getString(1) == name) {
                    return DocumentsContract.buildDocumentUriUsingTree(tree, cursor.getString(0))
                }
            }
        }
        return null
    }

    private fun create(folder: Uri, mimeType: String, name: String): Uri =
        DocumentsContract.createDocument(resolver, folder, mimeType, name)
            ?: throw IOException("Could not create $name")

    /**
     * The type that maps back to the extension of [name], so the provider keeps the name as it is
     * instead of adding an extension of its own.
     */
    private fun mimeTypeOf(name: String): String =
        MimeTypeMap.getSingleton().getMimeTypeFromExtension(name.substringAfterLast('.', ""))
            ?: OCTET_STREAM

    /** A revoked grant or a removed folder is a failed write, not a crash. */
    private inline fun guarded(block: () -> Unit) {
        try {
            block()
        } catch (denied: SecurityException) {
            throw IOException(denied)
        } catch (invalid: IllegalArgumentException) {
            throw IOException(invalid)
        } catch (invalid: IllegalStateException) {
            throw IOException(invalid)
        }
    }

    private companion object {
        const val OCTET_STREAM = "application/octet-stream"
    }
}
