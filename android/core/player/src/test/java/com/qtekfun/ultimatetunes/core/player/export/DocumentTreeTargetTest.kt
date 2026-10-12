// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.export

import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

/** A folder tree in memory that behaves like a document provider (unique names on rename). */
class MemoryTree : DocumentTree {
    class Doc(var name: String, val parent: String?, val isFolder: Boolean) {
        var bytes = ByteArray(0)
    }

    val docs = linkedMapOf("root" to Doc("", null, true))
    private var next = 0
    var failWritesAfter: Int? = null
    var failDelete = false
    var failRename = false
    val deleted = mutableListOf<String>()

    /** Paths of the files, `a/b/c`, with their size. */
    val files: Map<String, Int>
        get() = docs.filterValues { !it.isFolder }.entries.associate { (id, _) ->
            pathOf(id) to docs.getValue(id).bytes.size
        }

    private fun pathOf(id: String): String {
        val doc = docs.getValue(id)
        val parent = doc.parent ?: return ""
        val up = pathOf(parent)
        return if (up.isEmpty()) doc.name else "$up/${doc.name}"
    }

    fun put(path: String, bytes: ByteArray) {
        var folder = "root"
        val names = path.split('/')
        names.dropLast(1).forEach { name ->
            folder = named(folder, name)?.id ?: create(folder, name, isFolder = true)
        }
        docs.getValue(create(folder, names.last(), isFolder = false)).bytes = bytes
    }

    override fun root(): String = "root"

    override fun children(folder: String): List<DocumentTree.Entry> =
        docs.entries.filter { it.value.parent == folder }.map {
            DocumentTree.Entry(
                it.key,
                it.value.name,
                it.value.isFolder,
                it.value.bytes.size.toLong()
            )
        }

    private fun named(folder: String, name: String): DocumentTree.Entry? =
        children(folder).firstOrNull { it.name == name }

    override fun create(folder: String, name: String, isFolder: Boolean): String {
        val id = "doc-${next++}"
        docs[id] = Doc(unique(folder, name), folder, isFolder)
        return id
    }

    override fun rename(document: String, name: String): String {
        if (failRename) throw IOException("no rename here")
        val doc = docs.getValue(document)
        doc.name = unique(doc.parent!!, name)
        return document
    }

    override fun nameOf(document: String): String? = docs[document]?.name

    override fun openOutput(document: String): OutputStream {
        val doc = docs.getValue(document)
        return object : ByteArrayOutputStream() {
            override fun write(b: ByteArray, off: Int, len: Int) {
                val limit = failWritesAfter
                if (limit != null && size() + len > limit) throw IOException("disk full")
                super.write(b, off, len)
            }

            override fun close() {
                doc.bytes = toByteArray()
            }
        }
    }

    override fun delete(document: String) {
        if (failDelete) throw IOException("cannot delete")
        deleted += docs.getValue(document).name
        docs.remove(document)
    }

    /** Like a real provider: a taken name gets " (1)". */
    private fun unique(folder: String, name: String): String {
        if (children(folder).none { it.name == name }) return name
        val base = name.substringBeforeLast('.')
        val ext = name.substringAfterLast('.', "")
        return generateSequence(1) { it + 1 }
            .map { if (ext.isEmpty()) "$base ($it)" else "$base ($it).$ext" }
            .first { candidate -> children(folder).none { it.name == candidate } }
    }
}

class DocumentTreeTargetTest {
    private val tree = MemoryTree()
    private val target = DocumentTreeTarget(tree)
    private val bytes = ByteArray(100) { it.toByte() }
    private val path = listOf("Artist", "Album", "01 - Song.opus")

    private fun write(content: InputStream = ByteArrayInputStream(bytes), length: Long = 100) =
        target.write(path, length, content)

    @Test
    fun `a new file is written under its name, folders created, no temporary file left`() {
        assertEquals(WriteOutcome.WRITTEN, write())

        assertEquals(mapOf("Artist/Album/01 - Song.opus" to 100), tree.files)
        assertEquals(2, tree.docs.values.count { it.isFolder && it.parent != null })
    }

    @Test
    fun `existing folders are reused, never recreated`() {
        tree.put("Artist/Album/cover.jpg", ByteArray(5))
        write()
        target.write(listOf("Artist", "Album", "02 - Other.opus"), 100, ByteArrayInputStream(bytes))

        assertEquals(
            setOf(
                "Artist/Album/cover.jpg",
                "Artist/Album/01 - Song.opus",
                "Artist/Album/02 - Other.opus"
            ),
            tree.files.keys
        )
        assertEquals(2, tree.docs.values.count { it.isFolder && it.parent != null })
    }

    @Test
    fun `an earlier export of the same size is left as it is`() {
        tree.put("Artist/Album/01 - Song.opus", ByteArray(100))

        assertEquals(WriteOutcome.ALREADY_EXPORTED, write())
        assertTrue(
            tree.docs.values.single { it.name == "01 - Song.opus" }.bytes.all {
                it ==
                    0.toByte()
            }
        )
    }

    @Test
    fun `another file with the name is never touched`() {
        tree.put("Artist/Album/01 - Song.opus", ByteArray(7))
        assertEquals(WriteOutcome.NAME_TAKEN, write())

        assertEquals(mapOf("Artist/Album/01 - Song.opus" to 7), tree.files)
    }

    @Test
    fun `a name taken while writing gives our file back`() {
        val racing = object : DocumentTree by tree {
            override fun rename(document: String, name: String): String {
                tree.put("Artist/Album/$name", ByteArray(3))
                return tree.rename(document, name)
            }
        }

        assertEquals(
            WriteOutcome.NAME_TAKEN,
            DocumentTreeTarget(racing).write(path, 100, ByteArrayInputStream(bytes))
        )
        assertEquals(mapOf("Artist/Album/01 - Song.opus" to 3), tree.files)
    }

    @Test
    fun `a failed write leaves nothing behind`() {
        tree.failWritesAfter = 10
        assertThrows(IOException::class.java) { write() }
        assertEquals(emptyMap<String, Int>(), tree.files)

        tree.failWritesAfter = null
        assertThrows(IOException::class.java) { write(length = 99) }
        assertEquals(emptyMap<String, Int>(), tree.files)

        tree.failRename = true
        tree.failDelete = true
        assertThrows(IOException::class.java) { write() }
    }

    @Test
    fun `a song that stops reading leaves nothing behind and says so`() {
        val broken = object : InputStream() {
            var at = 0

            override fun read(): Int = if (at++ <
                50
            ) {
                1
            } else {
                throw SourceReadException(IOException("gone"))
            }
        }

        assertThrows(SourceReadException::class.java) { write(broken) }
        assertEquals(emptyMap<String, Int>(), tree.files)
    }

    @Test
    fun `a file where a folder should be is a failed write`() {
        tree.put("Artist", ByteArray(1))

        assertThrows(IOException::class.java) { write() }
        assertEquals(mapOf("Artist" to 1), tree.files)
    }

    @Test
    fun `folders are found without case, like phone storage does`() {
        tree.put("artist/ALBUM/cover.jpg", ByteArray(5))

        assertEquals(WriteOutcome.WRITTEN, write())

        assertEquals(
            setOf("artist/ALBUM/cover.jpg", "artist/ALBUM/01 - Song.opus"),
            tree.files.keys
        )
        assertEquals(2, tree.docs.values.count { it.isFolder && it.parent != null })
    }

    @Test
    fun `an exact folder name wins over one that differs only in case`() {
        tree.put("artist/Album/a.txt", ByteArray(1))
        tree.put("Artist/Album/b.txt", ByteArray(1))

        write()

        assertTrue("Artist/Album/01 - Song.opus" in tree.files.keys)
    }

    @Test
    fun `a file that differs only in case is the same file`() {
        tree.put("Artist/Album/01 - SONG.opus", ByteArray(100))
        assertEquals(WriteOutcome.ALREADY_EXPORTED, write())

        val other = MemoryTree().apply { put("Artist/Album/01 - SONG.opus", ByteArray(7)) }
        assertEquals(
            WriteOutcome.NAME_TAKEN,
            DocumentTreeTarget(other).write(path, 100, ByteArrayInputStream(bytes))
        )
        assertEquals(mapOf("Artist/Album/01 - SONG.opus" to 7), other.files)
    }

    @Test
    fun `temporary files an interrupted export left are removed, nobody else's`() {
        val stale = ".ut-export-0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0.part"
        tree.put(stale, ByteArray(3))
        tree.put("Artist/Album/$stale", ByteArray(3))
        tree.put("Other/$stale", ByteArray(3))
        tree.put("Artist/Album/.ut-export-notes.part", ByteArray(2))
        tree.put("Artist/Album/ut-export-0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0.part", ByteArray(2))

        assertEquals(WriteOutcome.WRITTEN, write())

        assertEquals(
            setOf(
                "Other/$stale",
                "Artist/Album/.ut-export-notes.part",
                "Artist/Album/ut-export-0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0.part",
                "Artist/Album/01 - Song.opus"
            ),
            tree.files.keys
        )
    }

    @Test
    fun `a folder is swept once per export, and a sweep that fails does not stop it`() {
        val stale = ".ut-export-0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0.part"
        tree.put("Artist/Album/$stale", ByteArray(3))
        tree.failDelete = true
        assertEquals(WriteOutcome.WRITTEN, write())
        tree.failDelete = false

        target.write(listOf("Artist", "Album", "02 - Other.opus"), 100, ByteArrayInputStream(bytes))

        assertTrue("Artist/Album/$stale" in tree.files.keys)
        assertEquals(emptyList<String>(), tree.deleted)
    }
}
