// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.export

import android.Manifest
import android.content.ContentResolver
import android.net.Uri
import android.os.Bundle
import android.provider.DocumentsContract
import android.provider.DocumentsContract.Document
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.player.PlayableTrack
import com.qtekfun.ultimatetunes.core.player.export.DocumentTreeTarget
import com.qtekfun.ultimatetunes.core.player.export.ExportSource
import com.qtekfun.ultimatetunes.core.player.export.Exporter
import com.qtekfun.ultimatetunes.core.player.export.SafDocumentTree
import com.qtekfun.ultimatetunes.core.player.export.SkipReason
import com.qtekfun.ultimatetunes.core.player.export.SourceFile
import java.io.ByteArrayInputStream
import java.io.IOException
import java.io.InputStream
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/**
 * The export's Storage Access Framework writes (RF-14) on the device, against a real documents
 * provider of the test APK ([TestDocumentsProvider]) the app gets a tree grant for, as from the
 * system folder picker. No file of the phone is touched.
 */
@RunWith(AndroidJUnit4::class)
class SafExportTest {
    private val resolver: ContentResolver =
        InstrumentationRegistry.getInstrumentation().targetContext.contentResolver
    private val tree: Uri =
        DocumentsContract.buildTreeDocumentUri(
            TestDocumentsProvider.AUTHORITY,
            TestDocumentsProvider.ROOT
        )
    private val opus = ByteArray(4_000).also {
        "OggS".toByteArray().copyInto(it, 0)
        "OpusHead".toByteArray().copyInto(it, 28)
        it[3_999] = 7
    }
    private val files = mutableMapOf<SongId, ByteArray>()
    private var failReadAt: Int? = null

    private val source = ExportSource { id ->
        files[id]?.let { bytes ->
            val failAt = failReadAt
            val stream: InputStream = if (failAt == null) {
                ByteArrayInputStream(bytes)
            } else {
                object : InputStream() {
                    var at = 0

                    override fun read(): Int = if (at >=
                        failAt
                    ) {
                        throw IOException("gone")
                    } else {
                        bytes[at++].toInt() and 0xFF
                    }
                }
            }
            SourceFile(bytes.size.toLong(), stream)
        }
    }

    private fun exporter() = Exporter(source, DocumentTreeTarget(SafDocumentTree(resolver, tree)))

    private fun call(method: String, arg: String? = null, extras: Bundle? = null) {
        resolver.call(TestDocumentsProvider.AUTHORITY, method, arg, extras)
    }

    private fun song(id: String, title: String, number: Int, disc: Int? = null) = PlayableTrack(
        id = SongId(id),
        title = title,
        artist = "The Paper Lanterns",
        album = "Harbour Lights",
        trackNumber = number,
        discNumber = disc
    ).also { files[SongId(id)] = opus }

    /** Every file under the tree: path to bytes. */
    private fun listing(
        documentId: String = TestDocumentsProvider.ROOT,
        prefix: String = ""
    ): Map<String, ByteArray> {
        val children = DocumentsContract.buildChildDocumentsUriUsingTree(tree, documentId)
        val found = mutableMapOf<String, ByteArray>()
        resolver.query(children, null, null, null, null)!!.use { cursor ->
            val id = cursor.getColumnIndexOrThrow(Document.COLUMN_DOCUMENT_ID)
            val name = cursor.getColumnIndexOrThrow(Document.COLUMN_DISPLAY_NAME)
            val type = cursor.getColumnIndexOrThrow(Document.COLUMN_MIME_TYPE)
            while (cursor.moveToNext()) {
                val path = prefix + cursor.getString(name)
                val folder = cursor.getString(type) == Document.MIME_TYPE_DIR
                found += entriesOf(cursor.getString(id), path, folder)
            }
        }
        return found
    }

    /**
     * The tree grant, as the system folder picker gives it: reaching the provider takes the
     * shell's MANAGE_DOCUMENTS for a moment, then the app holds only the URI grant.
     */
    private fun entriesOf(id: String, path: String, folder: Boolean): Map<String, ByteArray> {
        if (folder) return listing(id, "$path/")
        val uri = DocumentsContract.buildDocumentUriUsingTree(tree, id)
        return mapOf(path to resolver.openInputStream(uri)!!.use { it.readBytes() })
    }

    @Before
    fun grant() = asShell {
        call(TestDocumentsProvider.RESET)
        call(TestDocumentsProvider.GRANT)
    }

    /** Test setup only: the provider's own calls need MANAGE_DOCUMENTS, which the shell has. */
    private fun asShell(block: () -> Unit) {
        val automation = InstrumentationRegistry.getInstrumentation().uiAutomation
        automation.adoptShellPermissionIdentity(Manifest.permission.MANAGE_DOCUMENTS)
        try {
            block()
        } finally {
            automation.dropShellPermissionIdentity()
        }
    }

    @Test
    fun songsAreWrittenInTheServersLayoutAndTwoDiscsNeverClash() {
        val report = exporter().export(
            listOf(
                song("lib-1", "Intro", 1),
                song("lib-2", "Intro", 1, disc = 2),
                song("lib-3", "Intro", 1, disc = 2)
            )
        )

        assertEquals(3, report.exported)
        val written = listing()
        assertEquals(
            setOf(
                "The Paper Lanterns/Harbour Lights/01 - Intro.opus",
                "The Paper Lanterns/Harbour Lights/2-01 - Intro.opus",
                "The Paper Lanterns/Harbour Lights/2-01 - Intro (lib-3).opus"
            ),
            written.keys
        )
        written.values.forEach { assertArrayEquals(opus, it) }
    }

    @Test
    fun filesAlreadyInTheFolderAreNeverTouched() {
        asShell {
            val other = Bundle().apply { putInt(TestDocumentsProvider.SIZE, 12) }
            call(
                TestDocumentsProvider.PUT,
                "The Paper Lanterns/Harbour Lights/01 - Taken.opus",
                other
            )
            val same = Bundle().apply { putInt(TestDocumentsProvider.SIZE, opus.size) }
            call(
                TestDocumentsProvider.PUT,
                "The Paper Lanterns/Harbour Lights/02 - Earlier.opus",
                same
            )
        }

        val report = exporter().export(
            listOf(song("lib-1", "Taken", 1), song("lib-2", "Earlier", 2))
        )

        assertEquals(1, report.exported)
        assertEquals(listOf(SkipReason.ALREADY_IN_FOLDER), report.skipped.map { it.reason })
        val written = listing()
        assertEquals(2, written.size)
        assertEquals(12, written.getValue("The Paper Lanterns/Harbour Lights/01 - Taken.opus").size)
        // The earlier export of the same size is left as it was (zeros), not rewritten.
        assertEquals(
            0,
            written.getValue("The Paper Lanterns/Harbour Lights/02 - Earlier.opus").count {
                it !=
                    0.toByte()
            }
        )
    }

    @Test
    fun aSongThatStopsReadingLeavesNoFileBehind() {
        failReadAt = 2_000

        val report = exporter().export(listOf(song("lib-1", "Broken", 1)))

        assertEquals(listOf(SkipReason.NOT_ON_PHONE), report.skipped.map { it.reason })
        assertEquals(emptySet<String>(), listing().keys)
    }
}
