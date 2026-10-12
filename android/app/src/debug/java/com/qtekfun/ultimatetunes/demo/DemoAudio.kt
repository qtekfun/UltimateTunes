// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.demo

import java.io.ByteArrayOutputStream
import kotlin.math.PI
import kotlin.math.min
import kotlin.math.sin

/**
 * What the demo streams for every song: a soft generated chord that swells and fades every few
 * seconds, as long as the song says it is, so the player's times match the list. It is a FLAC
 * file (16-bit mono, verbatim frames: no compression, nothing clever), one of the formats the
 * server keeps, so a demo song can also be exported. No recording is bundled.
 */
@Suppress("MagicNumber") // Audio and FLAC format constants.
internal object DemoAudio {
    const val CONTENT_TYPE = "audio/flac"
    const val SUFFIX = "flac"

    private const val SAMPLE_RATE = 11_025

    /** Kilobits per second of the audio frames. */
    const val BIT_RATE = SAMPLE_RATE * 16 / 1000

    private const val LOOP_SECONDS = 8
    private const val DEFAULT_SECONDS = 30
    private const val MAX_SECONDS = 600
    private const val BLOCK = 4096

    /** "fLaC" + metadata block header + STREAMINFO. */
    private const val HEADER_BYTES = 4 + 4 + 34

    /** A frame without its number and samples: 4 + 2 (block size) + 1 (CRC-8) + 1 + 2 (CRC-16). */
    private const val FRAME_FIXED_BYTES = 10

    private val CHORD = doubleArrayOf(261.63, 329.63, 392.0)

    /** One swell of the chord, as 16-bit samples. */
    private val loop: ShortArray by lazy { buildLoop() }

    @Volatile
    private var last: Pair<Int, ByteArray>? = null

    /** The file for a song of [seconds] (30 s when unknown, at most 10 min). */
    fun flac(seconds: Int?): ByteArray {
        val length = clamp(seconds)
        last?.let { (cached, bytes) -> if (cached == length) return bytes }
        return build(length).also { last = length to it }
    }

    /** The exact size of [flac] for [seconds], without building it. */
    fun sizeOf(seconds: Int?): Long {
        val samples = clamp(seconds) * SAMPLE_RATE
        val frames = (samples + BLOCK - 1) / BLOCK
        var size = HEADER_BYTES.toLong() + samples * 2L
        for (n in 0 until frames) size += FRAME_FIXED_BYTES + utf8(n).size
        return size
    }

    private fun clamp(seconds: Int?) = (seconds ?: DEFAULT_SECONDS).coerceIn(1, MAX_SECONDS)

    private fun build(seconds: Int): ByteArray {
        val samples = seconds * SAMPLE_RATE
        val out = ByteArrayOutputStream(sizeOf(seconds).toInt())
        out.write("fLaC".toByteArray())
        // STREAMINFO, the only (so last) metadata block: 34 bytes.
        out.write(byteArrayOf(0x80.toByte(), 0, 0, 34))
        out.write(be(BLOCK.toLong(), 2))
        out.write(be(BLOCK.toLong(), 2))
        out.write(be(0, 3)) // Smallest frame: unknown.
        out.write(be(0, 3)) // Largest frame: unknown.
        // 20 bits rate, 3 bits channels - 1 (0), 5 bits bits per sample - 1 (15), 36 bits samples.
        val packed = (SAMPLE_RATE.toLong() shl 44) or (15L shl 36) or samples.toLong()
        out.write(be(packed, 8))
        out.write(ByteArray(16)) // MD5 of the audio: unknown (allowed).
        var start = 0
        var frame = 0
        while (start < samples) {
            val count = min(BLOCK, samples - start)
            out.write(frame(frame++, start, count))
            start += count
        }
        return out.toByteArray()
    }

    /** One frame: header, a verbatim mono subframe of [count] samples from [start], CRC-16. */
    private fun frame(number: Int, start: Int, count: Int): ByteArray {
        val bytes = ByteArrayOutputStream()
        // Sync, fixed block size; block size in 16 bits after the number, rate from STREAMINFO,
        // mono, 16 bits per sample.
        bytes.write(byteArrayOf(0xFF.toByte(), 0xF8.toByte(), 0x70, 0x08))
        bytes.write(utf8(number))
        bytes.write(be((count - 1).toLong(), 2))
        bytes.write(crc8(bytes.toByteArray()))
        bytes.write(0x02) // Verbatim subframe, no wasted bits.
        for (i in start until start + count) {
            val sample = loop[i % loop.size].toInt()
            bytes.write(sample shr 8)
            bytes.write(sample)
        }
        val crc = crc16(bytes.toByteArray())
        bytes.write(crc shr 8)
        bytes.write(crc)
        return bytes.toByteArray()
    }

    private fun buildLoop(): ShortArray {
        val samples = SAMPLE_RATE * LOOP_SECONDS
        val fade = SAMPLE_RATE / 2
        return ShortArray(samples) { i ->
            val t = i.toDouble() / SAMPLE_RATE
            val envelope = min(1.0, min(i, samples - i).toDouble() / fade)
            val value = CHORD.sumOf { sin(2 * PI * it * t) } / CHORD.size
            (value * envelope * 0.2 * Short.MAX_VALUE).toInt().toShort()
        }
    }

    private fun be(value: Long, bytes: Int) =
        ByteArray(bytes) { (value shr (8 * (bytes - 1 - it))).toByte() }

    /** The frame number in FLAC's UTF-8-like coding (16 bits are all a demo needs). */
    private fun utf8(n: Int): ByteArray = when {
        n < 0x80 -> byteArrayOf(n.toByte())

        n < 0x800 -> byteArrayOf((0xC0 or (n shr 6)).toByte(), (0x80 or (n and 0x3F)).toByte())

        else -> byteArrayOf(
            (0xE0 or (n shr 12)).toByte(),
            (0x80 or ((n shr 6) and 0x3F)).toByte(),
            (0x80 or (n and 0x3F)).toByte()
        )
    }

    private fun crc8(data: ByteArray): Int {
        var crc = 0
        for (b in data) {
            crc = crc xor (b.toInt() and 0xFF)
            repeat(8) { crc = if (crc and 0x80 != 0) (crc shl 1) xor 0x07 else crc shl 1 }
            crc = crc and 0xFF
        }
        return crc
    }

    private fun crc16(data: ByteArray): Int {
        var crc = 0
        for (b in data) {
            crc = crc xor ((b.toInt() and 0xFF) shl 8)
            repeat(8) { crc = if (crc and 0x8000 != 0) (crc shl 1) xor 0x8005 else crc shl 1 }
            crc = crc and 0xFFFF
        }
        return crc
    }
}
