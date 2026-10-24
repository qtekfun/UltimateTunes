// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.player

import androidx.annotation.DrawableRes
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.background
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
import androidx.compose.foundation.shape.CircleShape
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
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.blur
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.RectangleShape
import androidx.compose.ui.graphics.graphicsLayer
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
import androidx.compose.ui.text.font.FontWeight
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
import kotlinx.coroutines.launch

/** Test tags of the full player. */
const val FULL_PLAYER_TAG = "player.full"
const val LYRICS_BUTTON_TAG = "player.lyricsButton"
const val PLAYER_RADIO_TAG = "player.radio"
const val PLAYER_MORE_TAG = "player.more"
const val PLAYER_NOTE_TAG = "player.note"
const val PLAYER_SCRUBBER_TAG = "player.scrubber"

/** Opacity of the artwork behind the lyrics. */
private const val DIMMED_ARTWORK_ALPHA = 0.25f

/** Where the artwork starts fading into the background, as a share of its height. */
private const val ARTWORK_FADE_START = 0.45f

/** Ground of the buttons over the artwork, so they read on any cover. */
private const val OVER_ARTWORK_ALPHA = 0.28f

private val PlayButtonSize = 84.dp

/**
 * The full player (SPEC §5): the artwork edge to edge at the top, fading into its own colours,
 * a large title, a bar scrubber, the controls, the line of the lyrics being sung and the song
 * that plays next. Dragging down moves it with the finger and, past a threshold or with a fast
 * flick, closes it, as [onCollapse] does. [shown] is false while it slides away; showing it again
 * puts it back in place.
 */
@Composable
fun FullPlayer(
    state: PlayerUiState,
    actions: PlayerActions,
    onCollapse: () -> Unit,
    modifier: Modifier = Modifier,
    shown: Boolean = true,
    lyrics: LyricsHooks = LyricsHooks()
) {
    val track = state.current ?: return
    val trackMenu = LocalTrackMenu.current
    val colors = rememberPlayerColors(track.coverUrl)
    var showQueue by rememberSaveable { mutableStateOf(false) }
    var showLyrics by rememberSaveable { mutableStateOf(false) }
    val onShowLyrics by rememberUpdatedState(lyrics.onShow)
    // Loaded while the player is open, for the lyrics card as well as the full lyrics.
    LaunchedEffect(track.id, shown) { if (shown) onShowLyrics(track.id) }
    val collapse by rememberUpdatedState(onCollapse)
    val drag = rememberCollapseDrag(shown)

    Box(
        modifier = modifier
            .fillMaxSize()
            .graphicsLayer { translationY = drag.offset.value }
            .background(colors.bottom)
            .collapseOnDrag(drag) { collapse() }
            .testTag(FULL_PLAYER_TAG)
    ) {
        HeroArtwork(track, colors.bottom, dimmed = showLyrics)
        CompositionLocalProvider(LocalContentColor provides colors.content) {
            PlayerContent(
                state = state,
                actions = actions,
                onCollapse = onCollapse,
                colors = colors,
                panels = PlayerPanels(
                    showLyrics = showLyrics,
                    lyrics = lyrics,
                    onToggleLyrics = { showLyrics = !showLyrics },
                    onShowQueue = { showQueue = true },
                    onMore = trackMenu
                )
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
    colors: PlayerColors,
    panels: PlayerPanels,
    modifier: Modifier = Modifier
) {
    val track = state.current ?: return
    Column(
        modifier = modifier
            .fillMaxSize()
            .safeDrawingPadding()
    ) {
        TopBar(
            track = track,
            onCollapse = onCollapse,
            onRadio = actions.startRadio,
            onMore = { panels.onMore(track) }
        )
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
                    .padding(horizontal = Dimens.SpaceXL)
            )
        } else {
            Spacer(Modifier.weight(1f))
        }
        Column(modifier = Modifier.padding(horizontal = Dimens.SpaceXL)) {
            TrackTitle(state, colors.accent)
            PlaybackNote(state)
            BarScrubber(
                state,
                seed = track.id.value,
                accent = colors.accent,
                onSeek = actions.seekTo
            )
            Controls(state, actions, colors, panels)
            if (!panels.showLyrics) {
                LyricsCard(
                    lyrics = panels.lyrics.state,
                    track = track,
                    positionMillis = state.positionMs,
                    onOpen = panels.onToggleLyrics
                )
            }
            UpNextRow(state, panels.onShowQueue)
        }
    }
}

/**
 * The artwork across the whole width at the top, fading into [bottom]; faint behind the lyrics.
 */
@Composable
private fun HeroArtwork(track: TrackTile, bottom: Color, dimmed: Boolean) {
    val alpha by animateFloatAsState(
        targetValue = if (dimmed) DIMMED_ARTWORK_ALPHA else 1f,
        label = "artworkAlpha"
    )
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .aspectRatio(1f)
            .alpha(alpha)
    ) {
        Artwork(
            url = track.coverUrl,
            placeholderKey = track.id.value,
            shape = RectangleShape,
            modifier = Modifier.fillMaxSize()
        )
        Box(
            Modifier
                .fillMaxSize()
                .background(
                    Brush.verticalGradient(
                        ARTWORK_FADE_START to Color.Transparent,
                        1f to bottom
                    )
                )
        )
    }
}

/** Close, the album, and over the artwork the radio and the song's menu. */
@Composable
private fun TopBar(
    track: TrackTile,
    onCollapse: () -> Unit,
    onRadio: () -> Unit,
    onMore: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = Dimens.SpaceL, vertical = Dimens.SpaceS),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(Dimens.SpaceS)
    ) {
        RoundIconButton(
            icon = R.drawable.ic_chevron_down,
            label = stringResource(R.string.player_close),
            onClick = onCollapse
        )
        Box(modifier = Modifier.weight(1f), contentAlignment = Alignment.Center) {
            track.album?.let { album ->
                Text(
                    text = album,
                    style = MaterialTheme.typography.labelLarge,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier
                        .clip(Dimens.PillShape)
                        .background(Color.Black.copy(alpha = OVER_ARTWORK_ALPHA))
                        .padding(horizontal = Dimens.SpaceM, vertical = Dimens.SpaceS)
                )
            }
        }
        RoundIconButton(
            icon = R.drawable.ic_radio,
            label = stringResource(R.string.player_start_radio),
            onClick = onRadio,
            modifier = Modifier.testTag(PLAYER_RADIO_TAG)
        )
        RoundIconButton(
            icon = R.drawable.ic_more,
            label = stringResource(R.string.more_options),
            onClick = onMore,
            modifier = Modifier.testTag(PLAYER_MORE_TAG)
        )
    }
}

@Composable
private fun RoundIconButton(
    @DrawableRes icon: Int,
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    IconButton(
        onClick = onClick,
        modifier = modifier
            .size(44.dp)
            .clip(CircleShape)
            .background(Color.Black.copy(alpha = OVER_ARTWORK_ALPHA))
    ) {
        Icon(painter = painterResource(icon), contentDescription = label)
    }
}

@Composable
private fun TrackTitle(state: PlayerUiState, accent: Color) {
    val track = state.current ?: return
    Column(modifier = Modifier.fillMaxWidth()) {
        Text(
            text = track.title,
            style = MaterialTheme.typography.headlineMedium,
            fontWeight = FontWeight.ExtraBold,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.semantics { heading() }
        )
        Text(
            text = track.artist,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
            color = accent,
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

/** Lyrics, previous, play (round, in the accent), next and the queue. */
@Composable
private fun Controls(
    state: PlayerUiState,
    actions: PlayerActions,
    colors: PlayerColors,
    panels: PlayerPanels
) {
    val content = LocalContentColor.current
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = Dimens.SpaceM),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically
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
                tint = if (panels.showLyrics) colors.accent else content.copy(alpha = 0.7f)
            )
        }
        IconButton(onClick = actions.previous, modifier = Modifier.size(56.dp)) {
            Icon(
                painter = painterResource(R.drawable.ic_skip_previous),
                contentDescription = stringResource(R.string.player_previous),
                modifier = Modifier.size(36.dp)
            )
        }
        PlayButton(state.isPlaying, colors, actions.togglePlay)
        IconButton(
            onClick = actions.next,
            enabled = state.hasNext,
            modifier = Modifier.size(56.dp)
        ) {
            Icon(
                painter = painterResource(R.drawable.ic_skip_next),
                contentDescription = stringResource(R.string.player_next),
                modifier = Modifier.size(36.dp)
            )
        }
        IconButton(onClick = panels.onShowQueue) {
            Icon(
                painter = painterResource(R.drawable.ic_queue),
                contentDescription = stringResource(R.string.player_show_queue),
                tint = content.copy(alpha = 0.7f)
            )
        }
    }
}

/** Play or pause: a round button in the accent, the icon in the background's colour. */
@Composable
private fun PlayButton(isPlaying: Boolean, colors: PlayerColors, onClick: () -> Unit) {
    Box(
        modifier = Modifier
            .size(PlayButtonSize)
            .clip(CircleShape)
            .background(colors.accent),
        contentAlignment = Alignment.Center
    ) {
        CompositionLocalProvider(LocalContentColor provides colors.bottom) {
            PlayPauseButton(
                isPlaying = isPlaying,
                onClick = onClick,
                modifier = Modifier.fillMaxSize(),
                iconModifier = Modifier.size(40.dp)
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
