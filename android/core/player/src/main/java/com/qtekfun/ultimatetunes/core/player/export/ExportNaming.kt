// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.export

import com.qtekfun.ultimatetunes.core.player.PlayableTrack
import java.text.Normalizer

/**
 * Where an exported song goes inside the folder the user picked (RF-14): the server's library
 * layout (`server/src/ultimatetunes/paths/library.py`, SPEC §11 T09) — `AlbumArtist/Album/NN -
 * Title.ext`, `D-NN` on discs after the first, `Title.ext` without a track number, and a
 * ` (<suffix>)` that tells apart two songs that would get the same name. Every part is sanitized
 * the same way so it is a valid name on any file system: NFKC, `/\\:*?"<>|` replaced by `_`,
 * control and invisible characters dropped, leading and trailing dots and spaces stripped,
 * Windows reserved names prefixed with `_`, at most [MAX_COMPONENT_BYTES] bytes of UTF-8.
 */
object ExportNaming {
    /** Longest name of one folder or file, in UTF-8 bytes. */
    const val MAX_COMPONENT_BYTES = 180

    const val UNKNOWN_ARTIST = "Unknown Artist"
    const val UNKNOWN_ALBUM = "Unknown Album"
    const val UNTITLED = "Untitled"

    private const val MAX_NUMBER = 999
    private const val MAX_SUFFIX_BYTES = 64
    private const val TRACK_DIGITS = 2
    private val FORBIDDEN = Regex("""[/\\:*?"<>|]""")
    private val RESERVED = Regex(
        """^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$""",
        RegexOption.IGNORE_CASE
    )

    /**
     * The folders and the file name of [track] with [extension] (without the dot), with
     * [suffix] added to the title when given.
     */
    fun pathOf(track: PlayableTrack, extension: String, suffix: String? = null): List<String> {
        val ext = sanitize(extension)
        val dotExt = if (ext.isEmpty()) "" else ".$ext"
        val tail = suffix?.let { " (${truncate(sanitize(it).ifEmpty { "x" }, MAX_SUFFIX_BYTES)})" }
            .orEmpty()
        val prefix = prefixOf(track.trackNumber, track.discNumber)
        val room = MAX_COMPONENT_BYTES - utf8(prefix) - utf8(dotExt) - utf8(tail)
        val title = truncate(sanitize(track.title).ifEmpty { UNTITLED }, room).trimEnd(' ', '.')
        val artist = track.albumArtist?.takeIf { sanitize(it).isNotEmpty() } ?: track.artist
        return listOf(
            sanitize(artist).ifEmpty { UNKNOWN_ARTIST },
            sanitize(track.album.orEmpty()).ifEmpty { UNKNOWN_ALBUM },
            prefix + title.ifEmpty { UNTITLED } + tail + dotExt
        )
    }

    /** `NN - `, `D-NN - ` from the second disc, or nothing without a track number. */
    private fun prefixOf(trackNumber: Int?, discNumber: Int?): String {
        val track = trackNumber?.takeIf { it in 1..MAX_NUMBER } ?: return ""
        val disc = discNumber?.takeIf { it in 2..MAX_NUMBER }
        val number = track.toString().padStart(TRACK_DIGITS, '0')
        return if (disc == null) "$number - " else "$disc-$number - "
    }

    private fun utf8(text: String): Int = text.toByteArray().size

    /** [name] as one safe path component (empty when nothing is left). */
    fun sanitize(name: String): String {
        val normalized = Normalizer.normalize(name, Normalizer.Form.NFKC)
            .replace(FORBIDDEN, "_")
            .let(::visibleOnly)
            .trim(' ', '.')
        val safe = if (RESERVED.matches(normalized)) "_$normalized" else normalized
        return truncate(safe, MAX_COMPONENT_BYTES).trimEnd(' ', '.')
    }

    /** [text] without control, format (zero-width, bidi) and other invisible characters. */
    private fun visibleOnly(text: String): String = buildString {
        text.codePoints().forEach { cp -> if (!isInvisible(cp)) appendCodePoint(cp) }
    }

    private fun isInvisible(codePoint: Int): Boolean =
        when (Character.getType(codePoint).toByte()) {
            Character.CONTROL, Character.FORMAT, Character.UNASSIGNED, Character.PRIVATE_USE,
            Character.SURROGATE, Character.LINE_SEPARATOR, Character.PARAGRAPH_SEPARATOR -> true

            else -> false
        }

    /** [text] cut to at most [maxBytes] of UTF-8, never inside a character. */
    private fun truncate(text: String, maxBytes: Int): String {
        if (text.toByteArray().size <= maxBytes) return text
        val out = StringBuilder()
        var used = 0
        var i = 0
        while (i < text.length) {
            val cp = text.codePointAt(i)
            val chars = Character.charCount(cp)
            val bytes = text.substring(i, i + chars).toByteArray().size
            if (used + bytes > maxBytes) break
            out.append(text, i, i + chars)
            used += bytes
            i += chars
        }
        return out.toString()
    }
}
