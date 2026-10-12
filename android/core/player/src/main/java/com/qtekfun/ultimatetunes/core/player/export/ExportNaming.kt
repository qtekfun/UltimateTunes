// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.export

import com.qtekfun.ultimatetunes.core.player.PlayableTrack
import java.text.Normalizer

/**
 * Where an exported song goes inside the folder the user picked (RF-14): `Artist/Album/NN -
 * Title.ext`, the server's library layout (SPEC §11, T09), with every part sanitized the same
 * way so it is a valid name on any file system: NFKC, `/\:*?"<>|` replaced by `_`, control and
 * invisible characters dropped, leading and trailing dots and spaces stripped, Windows reserved
 * names prefixed with `_`, at most [MAX_COMPONENT_BYTES] bytes of UTF-8.
 */
object ExportNaming {
    /** Longest name of one folder or file, in UTF-8 bytes. */
    const val MAX_COMPONENT_BYTES = 180

    const val UNKNOWN_ARTIST = "Unknown Artist"
    const val UNKNOWN_ALBUM = "Unknown Album"
    const val UNKNOWN_TITLE = "Unknown"

    private const val TRACK_DIGITS = 2
    private val FORBIDDEN = Regex("""[/\\:*?"<>|]""")
    private val RESERVED = Regex(
        """^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$""",
        RegexOption.IGNORE_CASE
    )

    /** The folders and the file name of [track] with [extension] (without the dot). */
    fun pathOf(track: PlayableTrack, extension: String): List<String> {
        val title = sanitize(track.title).ifEmpty { UNKNOWN_TITLE }
        val number = track.trackNumber?.takeIf { it > 0 }
            ?.toString()?.padStart(TRACK_DIGITS, '0')
        val ext = sanitize(extension)
        val suffix = if (ext.isEmpty()) "" else ".$ext"
        val base = if (number == null) title else "$number - $title"
        return listOf(
            sanitize(track.artist).ifEmpty { UNKNOWN_ARTIST },
            sanitize(track.album.orEmpty()).ifEmpty { UNKNOWN_ALBUM },
            truncate(base, MAX_COMPONENT_BYTES - suffix.toByteArray().size) + suffix
        )
    }

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
