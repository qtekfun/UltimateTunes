// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.player

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.ui.designsystem.Artwork
import com.qtekfun.ultimatetunes.ui.lyrics.LyricsContent
import com.qtekfun.ultimatetunes.ui.lyrics.LyricsUiState
import com.qtekfun.ultimatetunes.ui.lyrics.LyricsViewModel
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import com.qtekfun.ultimatetunes.ui.theme.Dimens

const val PLAYER_LYRICS_CARD_TAG = "player.lyricsCard"
const val PLAYER_UP_NEXT_TAG = "player.upNext"

private val CardShape = RoundedCornerShape(16.dp)

/** Opacity of the cards' ground and of their small labels. */
private const val CARD_ALPHA = 0.08f
private const val LABEL_ALPHA = 0.6f
private const val NEXT_LINE_ALPHA = 0.45f

/**
 * The two lines the lyrics card shows at [positionMillis]: the line being sung (the first one
 * before the song reaches it) and the one after it. Plain lyrics show their first two lines.
 * Null when there is nothing to show.
 */
fun lyricsPreview(content: LyricsContent?, positionMillis: Long): Pair<String, String?>? {
    val lines = content?.lines?.filter { it.text.isNotBlank() }.orEmpty()
    if (lines.isEmpty()) return null
    val at = if (content?.synced == true) {
        LyricsViewModel.activeLine(lines, positionMillis).coerceAtLeast(0)
    } else {
        0
    }
    return lines[at].text to lines.getOrNull(at + 1)?.text
}

/** The lyrics card under the controls, for the song now playing; tapping it opens the lyrics. */
@Composable
internal fun LyricsCard(
    lyrics: LyricsUiState,
    track: TrackTile,
    positionMillis: Long,
    onOpen: () -> Unit
) {
    if (lyrics.songId != track.id) return
    val content = (lyrics.content as? LoadState.Ready)?.value
    val (current, next) = lyricsPreview(content, positionMillis) ?: return
    val color = LocalContentColor.current
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(CardShape)
            .background(color.copy(alpha = CARD_ALPHA))
            .clickable(onClickLabel = stringResource(R.string.player_show_lyrics), onClick = onOpen)
            .padding(horizontal = Dimens.SpaceL, vertical = Dimens.SpaceM)
            .testTag(PLAYER_LYRICS_CARD_TAG),
        verticalArrangement = Arrangement.spacedBy(Dimens.SpaceXS)
    ) {
        CardLabel(stringResource(R.string.player_lyrics_label))
        Text(
            text = current,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Bold,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis
        )
        next?.let {
            Text(
                text = it,
                style = MaterialTheme.typography.bodyLarge,
                fontWeight = FontWeight.SemiBold,
                color = color.copy(alpha = NEXT_LINE_ALPHA),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
        }
    }
}

/** The song that plays next; tapping it opens the queue. Nothing when the queue ends here. */
@Composable
internal fun UpNextRow(state: PlayerUiState, onShowQueue: () -> Unit) {
    val next = state.upNext.firstOrNull() ?: return
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = Dimens.MinRowHeight)
            .clip(CardShape)
            .clickable(
                onClickLabel = stringResource(R.string.player_show_queue),
                onClick = onShowQueue
            )
            .padding(vertical = Dimens.SpaceS)
            .testTag(PLAYER_UP_NEXT_TAG),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(Dimens.SpaceM)
    ) {
        Artwork(
            url = next.coverUrl,
            placeholderKey = next.id.value,
            shape = RoundedCornerShape(6.dp),
            modifier = Modifier.size(40.dp)
        )
        Column(modifier = Modifier.weight(1f)) {
            CardLabel(stringResource(R.string.player_up_next))
            Text(
                text = stringResource(R.string.player_up_next_song, next.title, next.artist),
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.SemiBold,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
        }
        Icon(
            painter = painterResource(R.drawable.ic_chevron_right),
            contentDescription = null
        )
    }
}

@Composable
private fun CardLabel(text: String) {
    Text(
        text = text.uppercase(),
        style = MaterialTheme.typography.labelSmall,
        fontWeight = FontWeight.Bold,
        color = LocalContentColor.current.copy(alpha = LABEL_ALPHA)
    )
}
