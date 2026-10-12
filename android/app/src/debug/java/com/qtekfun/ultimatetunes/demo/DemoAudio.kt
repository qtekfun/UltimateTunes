// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.demo

import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.PI
import kotlin.math.min
import kotlin.math.sin

/**
 * What the demo streams for every song: a few seconds of a soft generated chord (16-bit mono
 * WAV), so playback has something to play. No recording is bundled.
 */
@Suppress("MagicNumber") // Audio format constants.
internal object DemoAudio {
    private const val SAMPLE_RATE = 22_050
    private const val SECONDS = 8
    private const val HEADER = 44
    private val CHORD = doubleArrayOf(261.63, 329.63, 392.0)

    val wav: ByteArray by lazy { build() }

    private fun build(): ByteArray {
        val samples = SAMPLE_RATE * SECONDS
        val data = samples * 2
        val buffer = ByteBuffer.allocate(HEADER + data).order(ByteOrder.LITTLE_ENDIAN)
        buffer.put("RIFF".toByteArray()).putInt(36 + data).put("WAVE".toByteArray())
        buffer.put("fmt ".toByteArray()).putInt(16).putShort(1).putShort(1)
        buffer.putInt(SAMPLE_RATE).putInt(SAMPLE_RATE * 2).putShort(2).putShort(16)
        buffer.put("data".toByteArray()).putInt(data)
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
