// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.demo

import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.PI
import kotlin.math.min
import kotlin.math.sin

/**
 * What the demo streams for every song: a soft generated chord (16-bit mono WAV) that swells and
 * fades every few seconds, as long as the song says it is, so the player's times match the list.
 * No recording is bundled.
 */
@Suppress("MagicNumber") // Audio format constants.
internal object DemoAudio {
    private const val SAMPLE_RATE = 11_025
    private const val LOOP_SECONDS = 8
    private const val DEFAULT_SECONDS = 30
    private const val MAX_SECONDS = 600
    private const val HEADER = 44
    private val CHORD = doubleArrayOf(261.63, 329.63, 392.0)

    /** One swell of the chord, as little-endian 16-bit samples. */
    private val loop: ByteArray by lazy { buildLoop() }

    @Volatile
    private var last: Pair<Int, ByteArray>? = null

    /** The WAV for a song of [seconds] (30 s when unknown, at most 10 min). */
    fun wav(seconds: Int?): ByteArray {
        val length = (seconds ?: DEFAULT_SECONDS).coerceIn(1, MAX_SECONDS)
        last?.let { (cached, bytes) -> if (cached == length) return bytes }
        return build(length).also { last = length to it }
    }

    private fun build(seconds: Int): ByteArray {
        val data = SAMPLE_RATE * seconds * 2
        val buffer = ByteBuffer.allocate(HEADER + data).order(ByteOrder.LITTLE_ENDIAN)
        buffer.put("RIFF".toByteArray()).putInt(36 + data).put("WAVE".toByteArray())
        buffer.put("fmt ".toByteArray()).putInt(16).putShort(1).putShort(1)
        buffer.putInt(SAMPLE_RATE).putInt(SAMPLE_RATE * 2).putShort(2).putShort(16)
        buffer.put("data".toByteArray()).putInt(data)
        var left = data
        while (left > 0) {
            val n = min(left, loop.size)
            buffer.put(loop, 0, n)
            left -= n
        }
        return buffer.array()
    }

    private fun buildLoop(): ByteArray {
        val samples = SAMPLE_RATE * LOOP_SECONDS
        val buffer = ByteBuffer.allocate(samples * 2).order(ByteOrder.LITTLE_ENDIAN)
        val fade = SAMPLE_RATE / 2
        for (i in 0 until samples) {
            val t = i.toDouble() / SAMPLE_RATE
            val envelope = min(1.0, min(i, samples - i).toDouble() / fade)
            val value = CHORD.sumOf { sin(2 * PI * it * t) } / CHORD.size
            buffer.putShort((value * envelope * 0.2 * Short.MAX_VALUE).toInt().toShort())
        }
        return buffer.array()
    }
}
