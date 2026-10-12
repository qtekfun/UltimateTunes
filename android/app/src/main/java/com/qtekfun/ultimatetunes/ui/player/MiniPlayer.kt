// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.player

import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.CustomAccessibilityAction
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.ui.designsystem.Artwork
import com.qtekfun.ultimatetunes.ui.preview.PreviewData
import com.qtekfun.ultimatetunes.ui.theme.Dimens
import com.qtekfun.ultimatetunes.ui.theme.UltimateTunesTheme

/** Test tag of the mini player. */
const val MINI_PLAYER_TAG = "player.mini"

/** Horizontal drag that skips (SPEC §5: swipe the mini player to skip). */
private val SwipeThreshold = 56.dp

/**
 * The mini player pinned above the tab bar: artwork, title, artist, play/pause and next. Tap opens
 * the full player; swipe left or right skips (also TalkBack actions).
 */
@Composable
fun MiniPlayer(
    state: PlayerUiState,
    actions: PlayerActions,
    onOpen: () -> Unit,
    modifier: Modifier = Modifier
) {
    val track = state.current ?: return
    Surface(
        shape = Dimens.CardShape,
        color = MaterialTheme.colorScheme.surfaceContainerHigh,
        shadowElevation = 6.dp,
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = Dimens.SpaceS, vertical = Dimens.SpaceXS)
            .testTag(MINI_PLAYER_TAG)
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(min = Dimens.MiniPlayerHeight)
                .clickable(onClickLabel = stringResource(R.string.player_open), onClick = onOpen)
                .swipeToSkip(actions)
                .padding(horizontal = Dimens.SpaceS, vertical = Dimens.SpaceS),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Artwork(
                url = track.coverUrl,
                placeholderKey = track.id.value,
                shape = Dimens.SmallArtworkShape,
                modifier = Modifier.size(Dimens.MiniArtwork)
            )
            Column(
                modifier = Modifier
                    .weight(1f)
                    .padding(horizontal = Dimens.SpaceM)
            ) {
                Text(
                    text = track.title,
                    style = MaterialTheme.typography.titleSmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                Text(
                    text = track.artist,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }
            PlayPauseButton(isPlaying = state.isPlaying, onClick = actions.togglePlay)
            IconButton(onClick = actions.next, enabled = state.hasNext) {
                Icon(
                    painterResource(R.drawable.ic_skip_next),
                    contentDescription = stringResource(R.string.player_next)
                )
            }
        }
    }
}

/** Swipe left for the next song, right for the previous one; the same as TalkBack actions. */
@Composable
private fun Modifier.swipeToSkip(actions: PlayerActions): Modifier {
    val current by rememberUpdatedState(actions)
    val threshold = with(LocalDensity.current) { SwipeThreshold.toPx() }
    val nextLabel = stringResource(R.string.player_next)
    val previousLabel = stringResource(R.string.player_previous)
    return this
        .pointerInput(threshold) {
            var total = 0f
            detectHorizontalDragGestures(
                onDragStart = { total = 0f },
                onDragEnd = {
                    when {
                        total < -threshold -> current.next()
                        total > threshold -> current.previous()
                    }
                }
            ) { _, dragAmount -> total += dragAmount }
        }
        .semantics {
            customActions = listOf(
                CustomAccessibilityAction(nextLabel) {
                    current.next()
                    true
                },
                CustomAccessibilityAction(previousLabel) {
                    current.previous()
                    true
                }
            )
        }
}

/** Play or pause, labelled for TalkBack with what it will do. */
@Composable
fun PlayPauseButton(
    isPlaying: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    iconModifier: Modifier = Modifier
) {
    IconButton(onClick = onClick, modifier = modifier) {
        Icon(
            painter = painterResource(if (isPlaying) R.drawable.ic_pause else R.drawable.ic_play),
            contentDescription = stringResource(
                if (isPlaying) R.string.player_pause else R.string.player_play
            ),
            modifier = iconModifier
        )
    }
}

@Preview(name = "Mini player", showBackground = true)
@Preview(
    name = "Mini player, dark, large font",
    showBackground = true,
    fontScale = 1.6f,
    uiMode = android.content.res.Configuration.UI_MODE_NIGHT_YES
)
@Composable
private fun MiniPlayerPreview() {
    UltimateTunesTheme {
        MiniPlayer(
            state = PlayerUiState(queue = PreviewData.tracks, isPlaying = true),
            actions = PlayerActions(),
            onOpen = {}
        )
    }
}
