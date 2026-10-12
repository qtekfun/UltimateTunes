// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.e2e

import androidx.annotation.OptIn
import androidx.media3.common.C
import androidx.media3.common.Format
import androidx.media3.common.MimeTypes
import androidx.media3.common.util.UnstableApi
import androidx.media3.decoder.DecoderInputBuffer
import androidx.media3.exoplayer.BaseRenderer
import androidx.media3.exoplayer.FormatHolder
import androidx.media3.exoplayer.RendererCapabilities
import androidx.media3.exoplayer.RenderersFactory
import java.util.concurrent.atomic.AtomicInteger

/**
 * An audio renderer that takes every sample the player extracts and drops it, without a codec.
 *
 * The end-to-end test plays through the real Media3 stack (OkHttp, caches, the Ogg extractor,
 * buffering, end of stream) but can skip the platform decoder: on the author's Pixel 8 every
 * `MediaCodec` creation currently crashes natively, the system media provider included (T20
 * report), which says nothing about this app. `samples` counts what reached the renderer.
 */
@OptIn(UnstableApi::class)
class DiscardingAudioRenderer : BaseRenderer(C.TRACK_TYPE_AUDIO) {
    val samples = AtomicInteger()
    private val formatHolder = FormatHolder()
    private val buffer = DecoderInputBuffer(DecoderInputBuffer.BUFFER_REPLACEMENT_MODE_NORMAL)
    private var ended = false

    override fun getName(): String = "DiscardingAudioRenderer"

    override fun supportsFormat(format: Format): Int = RendererCapabilities.create(
        if (MimeTypes.isAudio(format.sampleMimeType)) {
            C.FORMAT_HANDLED
        } else {
            C.FORMAT_UNSUPPORTED_TYPE
        }
    )

    override fun render(positionUs: Long, elapsedRealtimeUs: Long) {
        while (!ended) {
            buffer.clear()
            when (readSource(formatHolder, buffer, 0)) {
                C.RESULT_BUFFER_READ -> onSample()
                C.RESULT_FORMAT_READ -> Unit
                else -> return
            }
        }
    }

    private fun onSample() {
        if (buffer.isEndOfStream) ended = true else samples.incrementAndGet()
    }

    override fun onPositionReset(positionUs: Long, joining: Boolean, sampleStreamIsFinal: Boolean) {
        ended = false
    }

    override fun isReady(): Boolean = true

    override fun isEnded(): Boolean = ended

    companion object {
        /** A [RenderersFactory] with just [renderer]. */
        fun factory(renderer: DiscardingAudioRenderer): RenderersFactory =
            RenderersFactory { _, _, _, _, _ -> arrayOf(renderer) }
    }
}
