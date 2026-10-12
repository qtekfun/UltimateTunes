// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.export

import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.player.PlayableTrack
import java.io.BufferedInputStream
import java.io.IOException
import java.io.InputStream
import kotlinx.serialization.Serializable

/** Where an exported song's bytes come from: only songs fully on the phone (RF-14). */
fun interface ExportSource {
    /** The whole file of the library song [id], or null when it is not fully on the phone. */
    fun open(id: SongId): InputStream?
}

/** The folder the user picked (Storage Access Framework). */
fun interface ExportTarget {
    /**
     * Writes [content] to [path] (folders, then the file name), creating the folders and replacing
     * an earlier export of the same file.
     */
    @Throws(IOException::class)
    fun write(path: List<String>, content: InputStream)
}

/** Why a song was not exported. */
@Serializable
enum class SkipReason {
    /** Still a YouTube Music song: its bytes on the phone, if any, predate tagging. */
    NOT_IN_LIBRARY,

    /** Neither downloaded nor completely in the play cache. */
    NOT_ON_PHONE,

    /** Not one of the formats the server keeps. */
    UNKNOWN_FORMAT,

    /** The folder refused the file (full, removed, permission gone). */
    WRITE_FAILED
}

@Serializable
data class SkippedTrack(val track: PlayableTrack, val reason: SkipReason)

/** What an export did. */
@Serializable
data class ExportReport(val exported: Int, val skipped: List<SkippedTrack>) {
    val total: Int get() = exported + skipped.size
}

/**
 * Copies songs to the user's folder (RF-14): only library songs fully on the phone (an offline
 * download, or a library song complete in the play cache), byte for byte in their original
 * format with their tags, as `Artist/Album/NN - Title.ext`. A `yt:` song is exported under the
 * library id the server gave it ([aliases]); bytes cached under the `yt:` id are never used.
 */
class Exporter(private val source: ExportSource, private val target: ExportTarget) {
    /**
     * Exports [tracks] (each once), calling [onProgress] with the songs handled so far and the
     * total before each one and at the end.
     */
    fun export(
        tracks: List<PlayableTrack>,
        aliases: Map<SongId, SongId> = emptyMap(),
        onProgress: (done: Int, total: Int) -> Unit = { _, _ -> }
    ): ExportReport {
        val unique = tracks.distinctBy { it.id }
        val skipped = mutableListOf<SkippedTrack>()
        var exported = 0
        unique.forEachIndexed { index, track ->
            onProgress(index, unique.size)
            when (val reason = exportOne(track, aliases)) {
                null -> exported++
                else -> skipped += SkippedTrack(track, reason)
            }
        }
        onProgress(unique.size, unique.size)
        return ExportReport(exported, skipped)
    }

    private fun exportOne(track: PlayableTrack, aliases: Map<SongId, SongId>): SkipReason? {
        val id = if (track.id.isExternal) aliases[track.id] else track.id
        val stream = id?.let(source::open)
        return when {
            id == null -> SkipReason.NOT_IN_LIBRARY
            stream == null -> SkipReason.NOT_ON_PHONE
            else -> copy(track, stream)
        }
    }

    private fun copy(track: PlayableTrack, stream: InputStream): SkipReason? = try {
        BufferedInputStream(stream).use { input ->
            input.mark(AudioFormats.HEADER_BYTES)
            val header = input.readNBytesCompat(AudioFormats.HEADER_BYTES)
            input.reset()
            val extension = AudioFormats.extensionOf(header)
            if (extension == null) {
                SkipReason.UNKNOWN_FORMAT
            } else {
                write(ExportNaming.pathOf(track, extension), input)
            }
        }
    } catch (ignored: IOException) {
        // The cached file could not be read after all.
        SkipReason.NOT_ON_PHONE
    }

    private fun write(path: List<String>, input: InputStream): SkipReason? = try {
        target.write(path, input)
        null
    } catch (ignored: IOException) {
        SkipReason.WRITE_FAILED
    }

    /** Up to [count] bytes (fewer only at the end of the stream); minSdk 26 has no readNBytes. */
    private fun InputStream.readNBytesCompat(count: Int): ByteArray {
        val buffer = ByteArray(count)
        var read = 0
        while (read < count) {
            val n = read(buffer, read, count - read)
            if (n < 0) break
            read += n
        }
        return buffer.copyOf(read)
    }
}
