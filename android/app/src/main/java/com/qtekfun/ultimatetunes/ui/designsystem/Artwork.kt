// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.designsystem

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.Icon
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import coil3.compose.AsyncImage
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.ui.theme.ArtworkPlaceholders
import com.qtekfun.ultimatetunes.ui.theme.Dimens
import kotlin.math.absoluteValue

/** Width of the placeholder's note, relative to the artwork. */
private const val NOTE_FRACTION = 0.4f

/** The placeholder gradient of [key]: the same item always gets the same colours. */
fun placeholderBrush(key: String): Brush {
    val (start, end) = ArtworkPlaceholders[key.hashCode().absoluteValue % ArtworkPlaceholders.size]
    return Brush.linearGradient(listOf(start, end))
}

/**
 * Rounded artwork: the cover at [url] over a gradient placeholder with a note, which is all that
 * shows while loading, without a server or when the cover fails. Decorative by default (the title
 * next to it says what it is); pass [contentDescription] when it stands alone.
 */
@Composable
fun Artwork(
    url: String?,
    placeholderKey: String,
    modifier: Modifier = Modifier,
    shape: Shape = Dimens.ArtworkShape,
    contentDescription: String? = null
) {
    Box(
        modifier = modifier
            .clip(shape)
            .background(placeholderBrush(placeholderKey)),
        contentAlignment = Alignment.Center
    ) {
        Icon(
            painter = painterResource(R.drawable.ic_music_note),
            contentDescription = null,
            tint = Color.White.copy(alpha = 0.85f),
            modifier = Modifier.fillMaxWidth(fraction = NOTE_FRACTION)
        )
        if (url != null) {
            AsyncImage(
                model = url,
                contentDescription = contentDescription,
                contentScale = ContentScale.Crop,
                modifier = Modifier.fillMaxSize()
            )
        }
    }
}
