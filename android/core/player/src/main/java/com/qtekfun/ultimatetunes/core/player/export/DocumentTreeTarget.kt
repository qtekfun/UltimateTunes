// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.export

import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.util.UUID

/**
 * A folder tree the user granted (Storage Access Framework), by document id. [SafDocumentTree] is
 * the real one; every failure is an [IOException].
 */
interface DocumentTree {
    /** A document of a folder. */
    class Entry(val id: String, val name: String, val isFolder: Boolean, val size: Long?)

    /** The id of the folder the user picked. */
    @Throws(IOException::class)
    fun root(): String

    /** The documents directly in [folder]. */
    @Throws(IOException::class)
    fun children(folder: String): List<Entry>

    /** Creates a document (a folder for [isFolder]) in [folder]; its id. */
    @Throws(IOException::class)
    fun create(folder: String, name: String, isFolder: Boolean): String

    /** Renames [document] to [name]; its id afterwards (the folder may pick another name). */
    @Throws(IOException::class)
    fun rename(document: String, name: String): String

    @Throws(IOException::class)
    fun nameOf(document: String): String?

    @Throws(IOException::class)
    fun openOutput(document: String): OutputStream

    @Throws(IOException::class)
    fun delete(document: String)
}

/**
 * The folder the user picked (RF-14). It never deletes, replaces or renames a file it did not
 * write, and never changes an existing folder: a file is written under a temporary name, then
 * renamed to its final name; a name that is already taken is left alone (an earlier export of the
 * same size counts as done). Names are matched without case, like phone storage does, so an
 * existing `copper fern` folder is reused for `Copper Fern` (an exact match wins). Missing folders
 * are created.
 *
 * It deletes only its own temporary files: the one of a write that fails, and, the first time an
 * export (one instance) uses a folder, the `.ut-export-<uuid>.part` files an interrupted export
 * left there. Exports are queued one after another (ExportManager) and a stopped one ends between
 * two songs (Exporter), but a stopped worker's thread may still be finishing one song when the
 * next attempt sweeps: that song's temporary file may then be deleted under it, its write or
 * rename fails, and it is reported as not written. Nothing is left behind either way.
 */
class DocumentTreeTarget(private val tree: DocumentTree) : ExportTarget {
    private val folders = HashMap<List<String>, String>()
    private val swept = HashSet<String>()

    override fun write(path: List<String>, length: Long, content: InputStream): WriteOutcome {
        val folder = folderOf(path.dropLast(1))
        val name = path.last()
        val existing = named(listing(folder), name)
        return when {
            existing == null -> writeNew(folder, name, length, content)
            !existing.isFolder && existing.size == length -> WriteOutcome.ALREADY_EXPORTED
            else -> WriteOutcome.NAME_TAKEN
        }
    }

    private fun writeNew(
        folder: String,
        name: String,
        length: Long,
        content: InputStream
    ): WriteOutcome {
        var ours: String? = tree.create(
            folder,
            "$TEMP_PREFIX${UUID.randomUUID()}$TEMP_SUFFIX",
            false
        )
        try {
            val written = tree.openOutput(checkNotNull(ours)).use { content.copyTo(it) }
            if (written != length) throw IOException("Wrote $written of $length bytes")
            ours = tree.rename(checkNotNull(ours), name)
            // The name was taken meanwhile and the folder picked another one: give it back.
            if (tree.nameOf(ours) != name) return WriteOutcome.NAME_TAKEN
            ours = null
            return WriteOutcome.WRITTEN
        } finally {
            // Anything still ours here was not kept: never leave a stray file behind.
            ours?.let(::deleteOurs)
        }
    }

    /** The folder at [names] under the tree, creating the missing ones (never changing others). */
    private fun folderOf(names: List<String>): String {
        var folder = tree.root()
        for (depth in 1..names.size) {
            val parent = folder
            val name = names[depth - 1]
            folder = folders.getOrPut(names.subList(0, depth).toList()) {
                val child = named(listing(parent), name)
                when {
                    child == null -> tree.create(parent, name, isFolder = true)
                    child.isFolder -> child.id
                    else -> throw IOException("$name is a file, not a folder")
                }
            }
        }
        return folder
    }

    /**
     * The documents of [folder]. The first time this export lists it, the temporary files an
     * interrupted export left there are deleted (best effort) and left out.
     */
    private fun listing(folder: String): List<DocumentTree.Entry> {
        val children = tree.children(folder)
        if (!swept.add(folder)) return children
        val (stale, kept) = children.partition { !it.isFolder && TEMP_NAME.matches(it.name) }
        stale.forEach { deleteOurs(it.id) }
        return kept
    }

    /** The entry called [name]: exactly, or else without case (phone storage ignores it). */
    private fun named(entries: List<DocumentTree.Entry>, name: String): DocumentTree.Entry? =
        entries.firstOrNull { it.name == name }
            ?: entries.firstOrNull { it.name.equals(name, ignoreCase = true) }

    /** Best effort: a file this target wrote that could not be kept. */
    private fun deleteOurs(document: String) {
        try {
            tree.delete(document)
        } catch (ignored: IOException) {
            // Nothing more can be done; the original failure is what counts.
        }
    }

    private companion object {
        const val TEMP_PREFIX = ".ut-export-"
        const val TEMP_SUFFIX = ".part"

        /** Exactly the temporary names [writeNew] gives: nobody else's file matches. */
        val TEMP_NAME = Regex("""\.ut-export-[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}\.part""")
    }
}
