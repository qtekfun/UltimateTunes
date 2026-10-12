// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.export

import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.player.PlayableTrack
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Nested
import org.junit.jupiter.api.Test

class ExportTest {
    private fun track(
        id: String,
        title: String = "Lighthouse Keeper",
        artist: String = "The Paper Lanterns",
        album: String? = "Harbour Lights",
        number: Int? = 3,
        disc: Int? = null,
        albumArtist: String? = null
    ) = PlayableTrack(
        SongId(id),
        title,
        artist,
        album,
        trackNumber = number,
        discNumber = disc,
        albumArtist = albumArtist
    )

    @Nested
    inner class Naming {
        @Test
        fun `the server's layout - album artist, album and a numbered title`() {
            assertEquals(
                listOf("The Paper Lanterns", "Harbour Lights", "03 - Lighthouse Keeper.opus"),
                ExportNaming.pathOf(track("a"), "opus")
            )
            assertEquals(
                listOf("Various Artists", "Harbour Lights", "03 - Lighthouse Keeper.opus"),
                ExportNaming.pathOf(track("a", albumArtist = "Various Artists"), "opus")
            )
            assertEquals(
                "The Paper Lanterns",
                ExportNaming.pathOf(track("a", albumArtist = " "), "opus")[0]
            )
        }

        @Test
        fun `discs after the first number their songs D-NN`() {
            assertEquals(
                "2-04 - Intro.m4a",
                ExportNaming.pathOf(track("a", "Intro", number = 4, disc = 2), "m4a").last()
            )
            assertEquals(
                "04 - Intro.m4a",
                ExportNaming.pathOf(track("a", "Intro", number = 4, disc = 1), "m4a").last()
            )
            assertEquals(
                "Intro.m4a",
                ExportNaming.pathOf(track("a", "Intro", number = 0, disc = 2), "m4a").last()
            )
            assertEquals(
                "Intro.m4a",
                ExportNaming.pathOf(track("a", "Intro", number = 1000), "m4a").last()
            )
        }

        @Test
        fun `missing parts get the server's stand-ins`() {
            assertEquals(
                listOf("Unknown Artist", "Unknown Album", "Untitled.m4a"),
                ExportNaming.pathOf(
                    track("a", title = " ", artist = "...", album = null, number = null),
                    "m4a"
                )
            )
            assertEquals(
                "Song",
                ExportNaming.pathOf(track("a", title = "Song", number = null), "").last()
            )
        }

        @Test
        fun `a suffix tells apart two songs with one name and survives truncation`() {
            assertEquals(
                "03 - Lighthouse Keeper (lib-2).opus",
                ExportNaming.pathOf(track("a"), "opus", suffix = "lib-2").last()
            )
            val long = ExportNaming.pathOf(
                track("a", title = "x".repeat(300)),
                "opus",
                "lib-2"
            ).last()
            assertTrue(long.endsWith(" (lib-2).opus"))
            assertEquals(ExportNaming.MAX_COMPONENT_BYTES, long.toByteArray().size)
        }

        @Test
        fun `names are safe on any file system`() {
            assertEquals("AC_DC", ExportNaming.sanitize("AC/DC"))
            assertEquals("a_b_c_d_e_f_g_h_i", ExportNaming.sanitize("a\\b:c*d?e\"f<g>h|i"))
            assertEquals("Fiesta", ExportNaming.sanitize(" ..Fi\u200Bes\u0000ta.. "))
            assertEquals("_CON", ExportNaming.sanitize("CON"))
            assertEquals("_lpt1.txt", ExportNaming.sanitize("lpt1.txt"))
            assertEquals("fi", ExportNaming.sanitize("\uFB01"))
            assertEquals("_", ExportNaming.pathOf(track("a", artist = "../.."), "mp3")[0])
        }

        @Test
        fun `long names are cut to 180 bytes without splitting a character`() {
            val name = ExportNaming.sanitize("ñ".repeat(200))
            assertEquals(90, name.length)
            val file = ExportNaming
                .pathOf(track("a", title = "x".repeat(300), number = 12), "flac")
                .last()
            assertTrue(file.startsWith("12 - x") && file.endsWith(".flac"))
            assertEquals(ExportNaming.MAX_COMPONENT_BYTES, file.toByteArray().size)
            val emoji = ExportNaming.sanitize("\uD83C\uDFB5".repeat(60))
            assertEquals(45, emoji.codePointCount(0, emoji.length))
        }
    }

    @Nested
    inner class Formats {
        private fun header(vararg parts: Pair<Int, String>): ByteArray {
            val bytes = ByteArray(64)
            parts.forEach { (offset, text) -> text.toByteArray().copyInto(bytes, offset) }
            return bytes
        }

        @Test
        fun `the formats the server keeps are recognised from their first bytes`() {
            assertEquals("opus", AudioFormats.extensionOf(header(0 to "OggS", 28 to "OpusHead")))
            assertEquals("ogg", AudioFormats.extensionOf(header(0 to "OggS", 28 to "\u0001vorbis")))
            assertEquals("flac", AudioFormats.extensionOf(header(0 to "fLaC")))
            assertEquals("m4a", AudioFormats.extensionOf(header(4 to "ftypM4A ")))
            assertEquals("mp3", AudioFormats.extensionOf(header(0 to "ID3")))
            assertEquals("mp3", AudioFormats.extensionOf(byteArrayOf(0xFF.toByte(), 0xFB.toByte())))
        }

        @Test
        fun `anything else is unknown`() {
            assertNull(AudioFormats.extensionOf(ByteArray(0)))
            assertNull(AudioFormats.extensionOf(header(0 to "RIFF")))
            assertNull(AudioFormats.extensionOf(byteArrayOf(0xFF.toByte(), 0x10)))
            assertNull(AudioFormats.extensionOf(byteArrayOf(0x10, 0xFB.toByte())))
        }
    }

    @Nested
    inner class Copying {
        private val opus = ByteArray(200).also {
            "OggS".toByteArray().copyInto(it, 0)
            "OpusHead".toByteArray().copyInto(it, 28)
            it[199] = 42
        }
        private val files = mutableMapOf<SongId, ByteArray>()
        private val written = mutableMapOf<List<String>, ByteArray>()
        private val taken = mutableMapOf<List<String>, WriteOutcome>()
        private var failWrites = false
        private var failReadsAfter: Int? = null

        private val source = ExportSource { id ->
            files[id]?.let { bytes ->
                val failAt = failReadsAfter
                val stream = if (failAt == null) {
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
        private val target = ExportTarget { path, length, content ->
            taken[path]?.let { return@ExportTarget it }
            if (failWrites) throw IOException("full")
            val bytes = ByteArrayOutputStream().also { content.copyTo(it) }.toByteArray()
            assertEquals(length, bytes.size.toLong())
            written[path] = bytes
            WriteOutcome.WRITTEN
        }
        private val exporter = Exporter(source, target)

        @Test
        fun `songs fully on the phone are copied byte for byte, each once`() {
            files[SongId("lib-1")] = opus
            val progress = mutableListOf<Pair<Int, Int>>()

            val report = exporter.export(listOf(track("lib-1"), track("lib-1"))) { done, total ->
                progress += done to total
            }

            assertEquals(ExportReport(1, emptyList()), report)
            assertEquals(1, report.total)
            val copied = written.getValue(
                listOf("The Paper Lanterns", "Harbour Lights", "03 - Lighthouse Keeper.opus")
            )
            assertTrue(copied.contentEquals(opus))
            assertEquals(listOf(0 to 1, 1 to 1), progress)
        }

        @Test
        fun `two songs never get the same file - the later one gets its id`() {
            files[SongId("lib-1")] = opus
            files[SongId("lib-2")] = opus
            files[SongId("lib-3")] = opus
            val intro1 = track("lib-1", "Intro", number = 1, disc = 1)
            val intro2 = track("lib-2", "Intro", number = 1, disc = 2)
            val intro2Again = track("lib-3", "intro", number = 1, disc = 2)

            val report = exporter.export(listOf(intro1, intro2, intro2Again))

            assertEquals(3, report.exported)
            assertEquals(
                setOf("01 - Intro.opus", "2-01 - Intro.opus", "2-01 - intro (lib-3).opus"),
                written.keys.map { it.last() }.toSet()
            )
        }

        @Test
        fun `a file already in the folder is never touched`() {
            files[SongId("lib-1")] = opus
            files[SongId("lib-2")] = opus
            val path = ExportNaming.pathOf(track("lib-1"), "opus")
            taken[path] = WriteOutcome.NAME_TAKEN
            taken[ExportNaming.pathOf(track("lib-2", "Other"), "opus")] =
                WriteOutcome.ALREADY_EXPORTED

            val report = exporter.export(listOf(track("lib-1"), track("lib-2", "Other")))

            assertEquals(1, report.exported)
            assertEquals(listOf(SkipReason.ALREADY_IN_FOLDER), report.skipped.map { it.reason })
            assertTrue(written.isEmpty())
        }

        @Test
        fun `a yt song goes under its library id, or is skipped without one`() {
            files[SongId("lib-9")] = opus
            // Bytes cached under the yt: id predate tagging: never used.
            files[SongId("yt:Rb4Tn8wKx1c")] = opus
            files[SongId("yt:Qx7Lm2pZ0aB")] = opus

            val report = exporter.export(
                listOf(track("yt:Rb4Tn8wKx1c"), track("yt:Qx7Lm2pZ0aB", title = "Other")),
                aliases = mapOf(SongId("yt:Rb4Tn8wKx1c") to SongId("lib-9"))
            )

            assertEquals(1, report.exported)
            assertEquals(listOf(SkipReason.NOT_IN_LIBRARY), report.skipped.map { it.reason })
            assertEquals("Other", report.skipped.single().track.title)
        }

        @Test
        fun `songs not on the phone, of unknown format or not writable are listed`() {
            files[SongId("odd")] = ByteArray(100)
            files[SongId("ok")] = opus

            val missing = exporter.export(listOf(track("none"), track("odd")))
            assertEquals(
                listOf(SkipReason.NOT_ON_PHONE, SkipReason.UNKNOWN_FORMAT),
                missing.skipped.map { it.reason }
            )

            failWrites = true
            assertEquals(
                listOf(SkipReason.WRITE_FAILED),
                exporter.export(listOf(track("ok"))).skipped.map { it.reason }
            )
        }

        @Test
        fun `a song that cannot be read, even halfway through the copy, is not on the phone`() {
            files[SongId("ok")] = opus

            failReadsAfter = 0
            assertEquals(
                listOf(SkipReason.NOT_ON_PHONE),
                exporter.export(listOf(track("ok"))).skipped.map { it.reason }
            )
            failReadsAfter = 150
            assertEquals(
                listOf(SkipReason.NOT_ON_PHONE),
                exporter.export(listOf(track("ok"))).skipped.map { it.reason }
            )
            assertTrue(written.isEmpty())
        }
    }
}
