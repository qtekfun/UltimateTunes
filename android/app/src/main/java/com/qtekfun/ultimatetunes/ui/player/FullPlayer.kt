// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.player

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectVerticalDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.blur
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import coil3.compose.AsyncImage
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.ui.actions.LocalTrackMenu
import com.qtekfun.ultimatetunes.ui.designsystem.Artwork
import com.qtekfun.ultimatetunes.ui.designsystem.TrackRow
import com.qtekfun.ultimatetunes.ui.lyrics.LyricsHooks
import com.qtekfun.ultimatetunes.ui.lyrics.LyricsView
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import com.qtekfun.ultimatetunes.ui.model.formatDuration
import com.qtekfun.ultimatetunes.ui.preview.PreviewData
import com.qtekfun.ultimatetunes.ui.theme.Dimens
import com.qtekfun.ultimatetunes.ui.theme.UltimateTunesTheme
import kotlin.math.roundToInt

/** Test tags of the full player. */
const val FULL_PLAYER_TAG = "player.full"
const val LYRICS_BUTTON_TAG = "player.lyricsButton"
const val PLAYER_RADIO_TAG = "player.radio"
const val PLAYER_MORE_TAG = "player.more"
const val PLAYER_NOTE_TAG = "player.note"
const val PLAYER_SCRUBBER_TAG = "player.scrubber"

private const val MILLIS_PER_SECOND = 1000L

/** Downward drag that closes the full player. */
private val CollapseThreshold = 120.dp

/** How much of the blurred artwork shows through the colours. */
private const val BLURRED_ARTWORK_ALPHA = 0.45f

/** The artwork shrinks a little while paused. */
private const val PAUSED_ARTWORK_SCALE = 0.84f

/**
 * The full player (SPEC §5): big artwork, colours from the artwork over its blurred copy,
 * scrubber, controls and the queue sheet. [artworkModifier] carries the shared-element
 * transition from the mini player. Dragging down or [onCollapse] closes it.
 */
@Composable
fun FullPlayer(
    state: PlayerUiState,
    actions: PlayerActions,
    onCollapse: () -> Unit,
    modifier: Modifier = Modifier,
    artworkModifier: Modifier = Modifier,
    lyrics: LyricsHooks = LyricsHooks()
) {
    val track = state.current ?: return
    val trackMenu = LocalTrackMenu.current
    val colors = rememberPlayerColors(track.coverUrl)
    var showQueue by rememberSaveable { mutableStateOf(false) }
    var showLyrics by rememberSaveable { mutableStateOf(false) }
    val onShowLyrics by rememberUpdatedState(lyrics.onShow)
    LaunchedEffect(track.id, showLyrics) { if (showLyrics) onShowLyrics(track.id) }
    val collapse by rememberUpdatedState(onCollapse)
    val threshold = with(LocalDensity.current) { CollapseThreshold.toPx() }

    Box(
        modifier = modifier
            .fillMaxSize()
            .background(Brush.verticalGradient(listOf(colors.top, colors.bottom)))
            .pointerInput(threshold) {
                var total = 0f
                detectVerticalDragGestures(
                    onDragStart = { total = 0f },
                    onDragEnd = { if (total > threshold) collapse() }
                ) { _, dragAmount -> total += dragAmount }
            }
            .testTag(FULL_PLAYER_TAG)
    ) {
        BlurredBackground(track.coverUrl, colors.bottom)
        CompositionLocalProvider(LocalContentColor provides colors.content) {
            PlayerContent(
                state = state,
                actions = actions,
                onCollapse = onCollapse,
                panels = PlayerPanels(
                    showLyrics = showLyrics,
                    lyrics = lyrics,
                    onToggleLyrics = { showLyrics = !showLyrics },
                    onShowQueue = { showQueue = true },
                    onMore = trackMenu
                ),
                artworkModifier = artworkModifier
            )
        }
    }
    if (showQueue) {
        QueueSheet(
            state = state,
            onDismiss = { showQueue = false },
            onPlayAt = actions.playAt
        )
    }
}

/** The lyrics and queue toggles of the full player, and its song menu. */
private data class PlayerPanels(
    val showLyrics: Boolean,
    val lyrics: LyricsHooks,
    val onToggleLyrics: () -> Unit,
    val onShowQueue: () -> Unit,
    val onMore: (TrackTile) -> Unit
)

@Composable
private fun PlayerContent(
    state: PlayerUiState,
    actions: PlayerActions,
    onCollapse: () -> Unit,
    panels: PlayerPanels,
    modifier: Modifier = Modifier,
    artworkModifier: Modifier = Modifier
) {
    val track = state.current ?: return
    Column(
        modifier = modifier
            .fillMaxSize()
            .safeDrawingPadding()
            .padding(horizontal = Dimens.SpaceXL),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        IconButton(onClick = onCollapse) {
            Icon(
                painter = painterResource(R.drawable.ic_chevron_down),
                contentDescription = stringResource(R.string.player_close)
            )
        }
        if (panels.showLyrics) {
            LyricsView(
                state = panels.lyrics.state,
                positionMillis = state.positionMs,
                // Tap to seek only for library songs, whose files allow it (SPEC §5).
                canSeek = !track.isExternal && state.canSeek,
                onSeek = actions.seekTo,
                onRetry = panels.lyrics.onRetry,
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth()
            )
        } else {
            BigArtwork(
                state = state,
                artworkModifier = artworkModifier,
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth()
            )
        }
        TrackTitle(state)
        PlaybackNote(state)
        Scrubber(state, actions.seekTo)
        Controls(state, actions)
        PanelButtons(panels, onRadio = actions.startRadio, onMore = { panels.onMore(track) })
    }
}

/**
 * The artwork, blurred, behind everything (blur needs Android 12; older ones get the artwork
 * kept faint).
 */
@Composable
private fun BlurredBackground(coverUrl: String?, bottom: Color) {
    if (coverUrl != null) {
        AsyncImage(
            model = coverUrl,
            contentDescription = null,
            contentScale = ContentScale.Crop,
            modifier = Modifier
                .fillMaxSize()
                .blur(72.dp)
                .alpha(BLURRED_ARTWORK_ALPHA)
        )
    }
    Box(
        Modifier
            .fillMaxSize()
            .background(
                Brush.verticalGradient(listOf(Color.Transparent, bottom.copy(alpha = 0.8f)))
            )
    )
}

/** The big artwork, a little smaller while paused. */
@Composable
private fun BigArtwork(state: PlayerUiState, modifier: Modifier, artworkModifier: Modifier) {
    val track = state.current ?: return
    val scale by animateFloatAsState(
        targetValue = if (state.isPlaying) 1f else PAUSED_ARTWORK_SCALE,
        label = "artworkScale"
    )
    Box(
        modifier = modifier.padding(vertical = Dimens.SpaceL),
        contentAlignment = Alignment.Center
    ) {
        Artwork(
            url = track.coverUrl,
            placeholderKey = track.id.value,
            shape = Dimens.PlayerArtworkShape,
            modifier = artworkModifier
                .aspectRatio(1f, matchHeightConstraintsFirst = true)
                .graphicsLayer {
                    scaleX = scale
                    scaleY = scale
                }
                .shadow(elevation = 24.dp, shape = Dimens.PlayerArtworkShape)
        )
    }
}

/** Lyrics on the left; radio, the song's menu and the queue on the right. */
@Composable
private fun PanelButtons(panels: PlayerPanels, onRadio: () -> Unit, onMore: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        IconButton(
            onClick = panels.onToggleLyrics,
            modifier = Modifier.testTag(LYRICS_BUTTON_TAG)
        ) {
            Icon(
                painter = painterResource(R.drawable.ic_lyrics),
                contentDescription = stringResource(
                    if (panels.showLyrics) {
                        R.string.player_hide_lyrics
                    } else {
                        R.string.player_show_lyrics
                    }
                ),
                tint = if (panels.showLyrics) {
                    LocalContentColor.current
                } else {
                    LocalContentColor.current.copy(alpha = 0.6f)
                }
            )
        }
        Row {
            IconButton(onClick = onRadio, modifier = Modifier.testTag(PLAYER_RADIO_TAG)) {
                Icon(
                    painter = painterResource(R.drawable.ic_radio),
                    contentDescription = stringResource(R.string.player_start_radio)
                )
            }
            IconButton(onClick = onMore, modifier = Modifier.testTag(PLAYER_MORE_TAG)) {
                Icon(
                    painter = painterResource(R.drawable.ic_more),
                    contentDescription = stringResource(R.string.more_options)
                )
            }
            IconButton(onClick = panels.onShowQueue) {
                Icon(
                    painter = painterResource(R.drawable.ic_queue),
                    contentDescription = stringResource(R.string.player_show_queue)
                )
            }
        }
    }
}

@Composable
private fun TrackTitle(state: PlayerUiState) {
    val track = state.current ?: return
    Column(modifier = Modifier.fillMaxWidth()) {
        Text(
            text = track.title,
            style = MaterialTheme.typography.headlineSmall,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.semantics { heading() }
        )
        Text(
            text = track.artist,
            style = MaterialTheme.typography.bodyLarge,
            color = LocalContentColor.current.copy(alpha = 0.75f),
            maxLines = 1,
            overflow = TextOverflow.Ellipsis
        )
        if (track.isExternal) {
            Text(
                text = stringResource(R.string.not_in_library),
                style = MaterialTheme.typography.labelSmall,
                color = LocalContentColor.current.copy(alpha = 0.6f),
                modifier = Modifier.padding(top = Dimens.SpaceXS)
            )
        }
    }
}

@Composable
private fun Scrubber(state: PlayerUiState, onSeek: (Long) -> Unit) {
    val content = LocalContentColor.current
    // While dragging, the thumb follows the finger; the seek happens once, on release.
    var dragging by remember { mutableStateOf<Float?>(null) }
    val positionMs = dragging?.toLong() ?: state.positionMs
    val durationMs = state.durationMs.coerceAtLeast(0)
    val elapsed = formatDuration((positionMs / MILLIS_PER_SECOND).toInt())
    val total = formatDuration((durationMs / MILLIS_PER_SECOND).toInt())
    val label = stringResource(R.string.player_position)
    val position = stringResource(R.string.player_position_state, elapsed, total)
    Column(modifier = Modifier.fillMaxWidth().padding(top = Dimens.SpaceL)) {
        Slider(
            value = positionMs.coerceIn(0, durationMs.coerceAtLeast(1)).toFloat(),
            onValueChange = { dragging = it },
            onValueChangeFinished = {
                dragging?.let { onSeek(it.toLong()) }
                dragging = null
            },
            enabled = state.canSeek,
            valueRange = 0f..durationMs.coerceAtLeast(1).toFloat(),
            colors = SliderDefaults.colors(
                thumbColor = content,
                activeTrackColor = content,
                inactiveTrackColor = content.copy(alpha = 0.3f),
                disabledThumbColor = content.copy(alpha = 0.6f),
                disabledActiveTrackColor = content.copy(alpha = 0.6f),
                disabledInactiveTrackColor = content.copy(alpha = 0.2f)
            ),
            modifier = Modifier
                .testTag(PLAYER_SCRUBBER_TAG)
                .semantics {
                    contentDescription = label
                    stateDescription = position
                }
        )
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text(
                text = elapsed,
                style = MaterialTheme.typography.labelSmall,
                color = content.copy(alpha = 0.7f)
            )
            Text(
                text = stringResource(
                    R.string.player_remaining,
                    formatDuration(((durationMs - positionMs) / MILLIS_PER_SECOND).toInt())
                ),
                style = MaterialTheme.typography.labelSmall,
                color = content.copy(alpha = 0.7f)
            )
        }
    }
}

@Composable
private fun Controls(state: PlayerUiState, actions: PlayerActions) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = Dimens.SpaceL),
        horizontalArrangement = Arrangement.SpaceEvenly,
        verticalAlignment = Alignment.CenterVertically
    ) {
        IconButton(onClick = actions.previous, modifier = Modifier.size(64.dp)) {
            Icon(
                painter = painterResource(R.drawable.ic_skip_previous),
                contentDescription = stringResource(R.string.player_previous),
                modifier = Modifier.size(40.dp)
            )
        }
        PlayPauseButton(
            isPlaying = state.isPlaying,
            onClick = actions.togglePlay,
            modifier = Modifier.size(80.dp),
            iconModifier = Modifier.size(56.dp)
        )
        IconButton(
            onClick = actions.next,
            enabled = state.hasNext,
            modifier = Modifier.size(64.dp)
        ) {
            Icon(
                painter = painterResource(R.drawable.ic_skip_next),
                contentDescription = stringResource(R.string.player_next),
                modifier = Modifier.size(40.dp)
            )
        }
    }
}

/** "Playing Next": the rest of the queue; tapping a song jumps to it. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun QueueSheet(state: PlayerUiState, onDismiss: () -> Unit, onPlayAt: (Int) -> Unit) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = false)
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheetState) {
        Text(
            text = stringResource(R.string.player_queue),
            style = MaterialTheme.typography.titleLarge,
            modifier = Modifier
                .padding(horizontal = Dimens.ScreenMargin, vertical = Dimens.SpaceS)
                .semantics { heading() }
        )
        val upNext = state.upNext
        if (upNext.isEmpty()) {
            Text(
                text = stringResource(R.string.player_queue_empty),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(Dimens.ScreenMargin)
            )
        } else {
            LazyColumn {
                itemsIndexed(upNext, key = { i, t -> "$i-${t.id.value}" }) { i, track ->
                    TrackRow(
                        track = track,
                        onClick = {
                            onPlayAt(state.index + 1 + i)
                            onDismiss()
                        },
                        showDivider = i < upNext.lastIndex
                    )
                }
            }
        }
        Spacer(Modifier.height(Dimens.SpaceXL))
    }
}

@Preview(name = "Full player", showBackground = true, widthDp = 400, heightDp = 860)
@Preview(
    name = "Full player, large font",
    showBackground = true,
    widthDp = 400,
    heightDp = 860,
    fontScale = 1.6f
)
@Composable
private fun FullPlayerPreview() {
    UltimateTunesTheme {
        FullPlayer(
            state = PlayerUiState(
                queue = PreviewData.tracks,
                isPlaying = true,
                positionMs = 74_000,
                durationMs = 197_000,
                canSeek = true
            ),
            actions = PlayerActions(),
            onCollapse = {}
        )
    }
}
