// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.export

import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.player.PlayableTrack
import java.io.BufferedInputStream
import java.io.FilterInputStream
import java.io.IOException
import java.io.InputStream
import java.util.Locale
import kotlinx.serialization.Serializable

/** A song's whole file on the phone: its exact [length] and its bytes. */
class SourceFile(val length: Long, val content: InputStream)

/** Where an exported song's bytes come from: only songs fully on the phone (RF-14). */
fun interface ExportSource {
    /** The whole file of the library song [id], or null when it is not fully on the phone. */
    fun open(id: SongId): SourceFile?
}

/** What the folder did with one file. */
enum class WriteOutcome {
    /** Written under its name. */
    WRITTEN,

    /** The same file (same name and size) is there from an earlier export: left as it is. */
    ALREADY_EXPORTED,

    /** Another file holds the name: nothing was written and nothing was touched. */
    NAME_TAKEN
}

/** A failure to read the song's own bytes (not the folder's fault). */
class SourceReadException(cause: IOException) : IOException(cause)

/**
 * The folder the user picked (Storage Access Framework). It never deletes, replaces or renames
 * anything it did not write itself in this call, and never touches existing folders.
 */
fun interface ExportTarget {
    /**
     * Writes [content] ([length] bytes) to [path] (folders, then the file name), creating missing
     * folders. A failed write leaves nothing behind; a [SourceReadException] from [content] is
     * rethrown as it is.
     */
    @Throws(IOException::class)
    fun write(path: List<String>, length: Long, content: InputStream): WriteOutcome
}

/** Why a song was not exported. */
@Serializable
enum class SkipReason {
    /** Still a YouTube Music song: its bytes on the phone, if any, predate tagging. */
    NOT_IN_LIBRARY,

    /** Neither downloaded nor completely in the play cache, or its bytes could not be read. */
    NOT_ON_PHONE,

    /** Not one of the formats the server keeps. */
    UNKNOWN_FORMAT,

    /** Another file already has its name in the folder (left untouched). */
    ALREADY_IN_FOLDER,

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
 * format with their tags, named like the server's library ([ExportNaming]). A `yt:` song is
 * exported under the library id the server gave it ([aliases]); bytes cached under the `yt:` id
 * are never used. Two songs of one export never get the same name: a later one gets its id as a
 * suffix, like the server does.
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
        val names = HashSet<String>()
        var exported = 0
        unique.forEachIndexed { index, track ->
            onProgress(index, unique.size)
            when (val reason = exportOne(track, aliases, names)) {
                null -> exported++
                else -> skipped += SkippedTrack(track, reason)
            }
        }
        onProgress(unique.size, unique.size)
        return ExportReport(exported, skipped)
    }

    private fun exportOne(
        track: PlayableTrack,
        aliases: Map<SongId, SongId>,
        names: MutableSet<String>
    ): SkipReason? {
        val id = if (track.id.isExternal) aliases[track.id] else track.id
        val file = id?.let(source::open)
        return when {
            id == null -> SkipReason.NOT_IN_LIBRARY
            file == null -> SkipReason.NOT_ON_PHONE
            else -> copy(track, id, file, names)
        }
    }

    private fun copy(
        track: PlayableTrack,
        id: SongId,
        file: SourceFile,
        names: MutableSet<String>
    ): SkipReason? = try {
        BufferedInputStream(ReadGuard(file.content)).use { input ->
            input.mark(AudioFormats.HEADER_BYTES)
            val header = input.readNBytesCompat(AudioFormats.HEADER_BYTES)
            input.reset()
            val extension = AudioFormats.extensionOf(header)
            if (extension == null) {
                SkipReason.UNKNOWN_FORMAT
            } else {
                write(uniquePath(track, id, extension, names), file.length, input)
            }
        }
    } catch (ignored: SourceReadException) {
        // The song's bytes could not be read after all.
        SkipReason.NOT_ON_PHONE
    }

    /** [track]'s path, with its id as a suffix when this export already used that name. */
    private fun uniquePath(
        track: PlayableTrack,
        id: SongId,
        extension: String,
        names: MutableSet<String>
    ): List<String> {
        val plain = ExportNaming.pathOf(track, extension)
        // Phone storage compares names without case.
        if (names.add(key(plain))) return plain
        return ExportNaming.pathOf(track, extension, id.value).also { names += key(it) }
    }

    private fun key(path: List<String>) = path.joinToString("/").lowercase(Locale.ROOT)

    private fun write(path: List<String>, length: Long, input: InputStream): SkipReason? = try {
        when (target.write(path, length, input)) {
            WriteOutcome.WRITTEN, WriteOutcome.ALREADY_EXPORTED -> null
            WriteOutcome.NAME_TAKEN -> SkipReason.ALREADY_IN_FOLDER
        }
    } catch (failed: SourceReadException) {
        throw failed
    } catch (ignored: IOException) {
        SkipReason.WRITE_FAILED
    }

    /** Marks failures to read the song, so they are not taken for the folder's. */
    private class ReadGuard(input: InputStream) : FilterInputStream(input) {
        override fun read(): Int = guarded { super.read() }

        override fun read(b: ByteArray, off: Int, len: Int): Int =
            guarded { super.read(b, off, len) }

        private inline fun <T> guarded(block: () -> T): T = try {
            block()
        } catch (failed: SourceReadException) {
            throw failed
        } catch (failed: IOException) {
            throw SourceReadException(failed)
        }
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
