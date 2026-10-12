// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.export

import android.content.ContentResolver
import android.net.Uri
import android.provider.DocumentsContract
import android.provider.DocumentsContract.Document
import androidx.core.net.toUri
import java.io.IOException
import java.io.OutputStream

/**
 * [DocumentTree] over a tree URI granted with the system folder picker (RF-14): no storage
 * permission. A revoked grant, a removed folder or a provider without rename is an IOException.
 */
class SafDocumentTree(private val resolver: ContentResolver, private val tree: Uri) :
    DocumentTree {
    override fun root(): String = guarded {
        DocumentsContract.buildDocumentUriUsingTree(tree, DocumentsContract.getTreeDocumentId(tree))
            .toString()
    }

    override fun children(folder: String): List<DocumentTree.Entry> = guarded {
        val children = DocumentsContract.buildChildDocumentsUriUsingTree(
            tree,
            DocumentsContract.getDocumentId(folder.toUri())
        )
        val columns = arrayOf(
            Document.COLUMN_DOCUMENT_ID,
            Document.COLUMN_DISPLAY_NAME,
            Document.COLUMN_MIME_TYPE,
            Document.COLUMN_SIZE
        )
        val entries = mutableListOf<DocumentTree.Entry>()
        resolver.query(children, columns, null, null, null)?.use { cursor ->
            while (cursor.moveToNext()) {
                entries += DocumentTree.Entry(
                    id = DocumentsContract.buildDocumentUriUsingTree(tree, cursor.getString(0))
                        .toString(),
                    name = cursor.getString(1).orEmpty(),
                    isFolder = cursor.getString(2) == Document.MIME_TYPE_DIR,
                    size = if (cursor.isNull(SIZE)) null else cursor.getLong(SIZE)
                )
            }
        }
        entries
    }

    override fun create(folder: String, name: String, isFolder: Boolean): String = guarded {
        val type = if (isFolder) Document.MIME_TYPE_DIR else OCTET_STREAM
        DocumentsContract.createDocument(resolver, folder.toUri(), type, name)?.toString()
            ?: throw IOException("Could not create $name")
    }

    override fun rename(document: String, name: String): String = guarded {
        (DocumentsContract.renameDocument(resolver, document.toUri(), name) ?: document.toUri())
            .toString()
    }

    override fun nameOf(document: String): String? = guarded {
        resolver.query(
            document.toUri(),
            arrayOf(Document.COLUMN_DISPLAY_NAME),
            null,
            null,
            null
        )?.use { if (it.moveToFirst()) it.getString(0) else null }
    }

    override fun openOutput(document: String): OutputStream = guarded {
        resolver.openOutputStream(document.toUri(), "w") ?: throw IOException("Not writable")
    }

    override fun delete(document: String) {
        guarded { DocumentsContract.deleteDocument(resolver, document.toUri()) }
    }

    private inline fun <T> guarded(block: () -> T): T {
        try {
            return block()
        } catch (denied: SecurityException) {
            failed(denied)
        } catch (invalid: IllegalArgumentException) {
            failed(invalid)
        } catch (invalid: IllegalStateException) {
            failed(invalid)
        } catch (unsupported: UnsupportedOperationException) {
            failed(unsupported)
        }
    }

    private fun failed(cause: RuntimeException): Nothing = throw IOException(cause)

    private companion object {
        /**
         * The temporary file's type: with it the folder keeps the name as given, and the final
         * name's extension sets the type on rename.
         */
        const val OCTET_STREAM = "application/octet-stream"

        /** Column of the size in the children query. */
        const val SIZE = 3
    }
}
