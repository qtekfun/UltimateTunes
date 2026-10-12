// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.lyrics

import androidx.annotation.StringRes
import androidx.compose.animation.animateColorAsState
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.ui.designsystem.messageRes
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.theme.Dimens
import com.qtekfun.ultimatetunes.ui.theme.UltimateTunesTheme

/** Test tags of the lyrics view. */
const val LYRICS_TAG = "player.lyrics"
const val LYRICS_ACTIVE_LINE_TAG = "player.lyrics.active"

/** Lines kept above the active one when scrolling to it. */
private const val LINES_ABOVE_ACTIVE = 2

/** Opacity of the lines that are not being sung. */
private const val INACTIVE_ALPHA = 0.45f

private const val MILLIS_PER_SECOND = 1000L

/** The lyrics view's data and what it can do, as the player passes them. */
@Immutable
data class LyricsHooks(
    val state: LyricsUiState = LyricsUiState(),
    /** Asks for the lyrics of the song now playing. */
    val onShow: (SongId) -> Unit = {},
    val onRetry: () -> Unit = {}
)

/**
 * Lyrics full screen (SPEC §5): the line being sung highlighted and kept in view; tapping a synced
 * line seeks there when [canSeek] (the song is in the library, so its file supports seeking).
 */
@Composable
fun LyricsView(
    state: LyricsUiState,
    positionMillis: Long,
    canSeek: Boolean,
    onSeek: (Int) -> Unit,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier
) {
    Box(
        modifier = modifier.fillMaxSize().testTag(LYRICS_TAG),
        contentAlignment = Alignment.Center
    ) {
        when (val content = state.content) {
            LoadState.Loading -> CircularProgressIndicator(color = LocalContentColor.current)

            is LoadState.Failed -> ErrorMessage(content.error.messageRes(), onRetry)

            is LoadState.Ready -> {
                val lyrics = content.value
                if (lyrics == null || lyrics.lines.isEmpty()) {
                    Message(stringResource(R.string.lyrics_none))
                } else {
                    Lines(lyrics, positionMillis, canSeek && lyrics.synced, onSeek)
                }
            }
        }
    }
}

@Composable
private fun ErrorMessage(@StringRes message: Int, onRetry: () -> Unit) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Message(stringResource(message))
        TextButton(onClick = onRetry) {
            Text(stringResource(R.string.retry), color = LocalContentColor.current)
        }
    }
}

@Composable
private fun Message(text: String) {
    Text(
        text = text,
        style = MaterialTheme.typography.bodyLarge,
        color = LocalContentColor.current.copy(alpha = 0.75f),
        textAlign = TextAlign.Center,
        modifier = Modifier
            .padding(Dimens.SpaceXL)
            .semantics { liveRegion = LiveRegionMode.Polite }
    )
}

@Composable
private fun Lines(
    lyrics: LyricsContent,
    positionMillis: Long,
    canSeek: Boolean,
    onSeek: (Int) -> Unit
) {
    val active = LyricsViewModel.activeLine(lyrics.lines, positionMillis)
    val listState = rememberLazyListState()
    LaunchedEffect(active) {
        if (active >=
            0
        ) {
            listState.animateScrollToItem((active - LINES_ABOVE_ACTIVE).coerceAtLeast(0))
        }
    }
    val seekLabel = stringResource(R.string.lyrics_seek)
    LazyColumn(
        state = listState,
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(vertical = Dimens.SpaceXL)
    ) {
        itemsIndexed(lyrics.lines) { index, line ->
            val isActive = index == active
            val base = LocalContentColor.current
            val color by animateColorAsState(
                if (isActive || !lyrics.synced) base else base.copy(alpha = INACTIVE_ALPHA),
                label = "lyricColor"
            )
            val start = line.startMillis
            Text(
                text = line.text,
                style = if (lyrics.synced) {
                    MaterialTheme.typography.headlineSmall
                } else {
                    MaterialTheme.typography.titleMedium
                },
                fontWeight = if (isActive) FontWeight.Bold else FontWeight.SemiBold,
                color = color,
                modifier = Modifier
                    .fillMaxWidth()
                    .then(
                        if (canSeek && start != null) {
                            Modifier.clickable(onClickLabel = seekLabel) {
                                onSeek((start / MILLIS_PER_SECOND).toInt())
                            }
                        } else {
                            Modifier
                        }
                    )
                    .semantics { selected = isActive }
                    .then(if (isActive) Modifier.testTag(LYRICS_ACTIVE_LINE_TAG) else Modifier)
                    .padding(vertical = Dimens.SpaceS, horizontal = 4.dp)
            )
        }
    }
}

@Preview(
    name = "Lyrics, synced",
    showBackground = true,
    backgroundColor = 0xFF3A2A4A,
    heightDp = 600
)
@Composable
private fun LyricsPreview() {
    UltimateTunesTheme(darkTheme = true) {
        LyricsView(
            state = LyricsUiState(
                songId = SongId("preview-song-1"),
                content = LoadState.Ready(
                    LyricsContent(
                        lines = listOf(
                            LyricLineUi("Salt on the window, the night coming in", startMillis = 0),
                            LyricLineUi(
                                "I keep the light for the ships that never were",
                                startMillis = 4210
                            ),
                            LyricLineUi(
                                "Turning and turning, the harbour asleep",
                                startMillis = 9875
                            )
                        ),
                        synced = true
                    )
                )
            ),
            positionMillis = 5000,
            canSeek = true,
            onSeek = {},
            onRetry = {}
        )
    }
}
