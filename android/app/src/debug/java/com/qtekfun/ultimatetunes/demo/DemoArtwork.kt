// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.demo

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.Shader
import android.graphics.Typeface
import androidx.core.graphics.createBitmap
import java.io.ByteArrayOutputStream
import java.util.concurrent.ConcurrentHashMap
import kotlin.math.absoluteValue

/**
 * Generated placeholder covers for the demo: a diagonal gradient, a few soft circles and the
 * initials of [label], as PNG. Nothing is downloaded or bundled; same input, same picture.
 */
@Suppress("MagicNumber") // Drawing proportions.
internal object DemoArtwork {
    private val PALETTE = listOf(
        0xFFE0284F to 0xFFFF8A5C,
        0xFF5B4BE0 to 0xFF9F7CFF,
        0xFF0F8B8D to 0xFF52D1B2,
        0xFFDB7B12 to 0xFFFFC75F,
        0xFF2E6BE6 to 0xFF6FC3FF,
        0xFF7A3E9D to 0xFFE07AB8,
        0xFF1F2A44 to 0xFF4A6FA5,
        0xFF2F7D32 to 0xFFA5D66F
    )

    private const val MIN_SIZE = 64
    private const val MAX_SIZE = 1024
    private const val DEFAULT_SIZE = 600

    private val cache = ConcurrentHashMap<String, ByteArray>()

    /** The PNG of the cover of [label] at [size] pixels (clamped to 64..1024). */
    fun png(label: String, size: Int?): ByteArray {
        val px = (size ?: DEFAULT_SIZE).coerceIn(MIN_SIZE, MAX_SIZE)
        return cache.getOrPut("$px:$label") { render(label, px) }
    }

    private fun render(label: String, px: Int): ByteArray {
        val hash = label.hashCode().absoluteValue
        val (start, end) = PALETTE[hash % PALETTE.size]
        val bitmap = createBitmap(px, px)
        val canvas = Canvas(bitmap)
        val size = px.toFloat()
        val paint = Paint(Paint.ANTI_ALIAS_FLAG)
        paint.shader = LinearGradient(
            0f,
            0f,
            size,
            size,
            start.toInt(),
            end.toInt(),
            Shader.TileMode.CLAMP
        )
        canvas.drawRect(0f, 0f, size, size, paint)

        paint.shader = null
        paint.color = 0x22FFFFFF
        repeat(3) { i ->
            val seed = hash / (i + 1) / 7
            val cx = size * ((seed % 100) / 100f)
            val cy = size * (((seed / 100) % 100) / 100f)
            canvas.drawCircle(cx, cy, size * (0.25f + 0.15f * i), paint)
        }

        paint.color = 0xF2FFFFFF.toInt()
        paint.typeface = Typeface.create(Typeface.DEFAULT, Typeface.BOLD)
        paint.textAlign = Paint.Align.CENTER
        paint.textSize = size * 0.34f
        val text = initials(label)
        val baseline = size / 2 - (paint.descent() + paint.ascent()) / 2
        canvas.drawText(text, size / 2, baseline, paint)

        val out = ByteArrayOutputStream()
        bitmap.compress(Bitmap.CompressFormat.PNG, 100, out)
        bitmap.recycle()
        return out.toByteArray()
    }

    /** Up to two initials of the words of [label] that start with a letter. */
    fun initials(label: String): String = label
        .split(' ', '-', '(')
        .filter { word -> word.firstOrNull()?.isLetter() == true }
        .filterNot { it.lowercase() in SMALL_WORDS }
        .take(2)
        .joinToString("") { it.first().uppercase() }
        .ifEmpty { "UT" }

    private val SMALL_WORDS = setOf("the", "in", "to", "of", "and", "en", "la", "de", "del", "los")
}
