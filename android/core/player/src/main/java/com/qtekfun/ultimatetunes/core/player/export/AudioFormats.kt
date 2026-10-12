// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.export

/**
 * The format of an exported file, told from its first bytes, so export works with no network
 * (the server keeps original files only: Ogg/Opus, M4A, MP3, FLAC, Ogg; SPEC §11, T02/T09).
 */
object AudioFormats {
    /** Bytes [extensionOf] needs to tell the formats apart. */
    const val HEADER_BYTES = 64

    const val OPUS = "opus"
    const val OGG = "ogg"
    const val M4A = "m4a"
    const val MP3 = "mp3"
    const val FLAC = "flac"

    private const val OGG_PAGE_HEADER = 28
    private const val FTYP_OFFSET = 4
    private const val MPEG_SYNC = 0xFF
    private const val MPEG_SYNC_MASK = 0xE0

    /** The extension of a file starting with [header], or null when it is none of the above. */
    fun extensionOf(header: ByteArray): String? = when {
        header.startsWith("OggS") ->
            if (header.startsWith("OpusHead", OGG_PAGE_HEADER)) OPUS else OGG

        header.startsWith("fLaC") -> FLAC

        header.startsWith("ftyp", FTYP_OFFSET) -> M4A

        header.startsWith("ID3") -> MP3

        header.size >= 2 && header[0].toInt() and MPEG_SYNC == MPEG_SYNC &&
            header[1].toInt() and MPEG_SYNC_MASK == MPEG_SYNC_MASK -> MP3

        else -> null
    }

    private fun ByteArray.startsWith(text: String, offset: Int = 0): Boolean {
        val bytes = text.toByteArray(Charsets.US_ASCII)
        if (size < offset + bytes.size) return false
        return bytes.indices.all { this[offset + it] == bytes[it] }
    }
}
