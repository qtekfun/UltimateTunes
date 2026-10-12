// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.player

import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.playback.PlaybackIssue
import com.qtekfun.ultimatetunes.ui.theme.Dimens
import kotlin.math.roundToInt

private const val PERCENT = 100

/** How the player explains [this] issue. */
@StringRes
fun PlaybackIssue.messageRes(): Int = when (this) {
    PlaybackIssue.NETWORK -> R.string.player_issue_network
    PlaybackIssue.NOT_AVAILABLE -> R.string.player_issue_not_available
    PlaybackIssue.UNPLAYABLE -> R.string.player_issue_unplayable
}

/**
 * Under the title: how a first play is going while the server fetches the song (RF-05), or why
 * the song cannot play.
 */
@Composable
internal fun PlaybackNote(state: PlayerUiState) {
    val first = state.firstPlay
    val content = LocalContentColor.current
    val text = when {
        first != null && first.failed -> stringResource(R.string.player_first_play_failed)

        first != null -> stringResource(
            R.string.player_first_play_progress,
            (first.progress * PERCENT).roundToInt().coerceIn(0, PERCENT)
        )

        state.issue != null -> stringResource(state.issue.messageRes())

        else -> return
    }
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = Dimens.SpaceS)
            .testTag(PLAYER_NOTE_TAG)
            .semantics { liveRegion = LiveRegionMode.Polite }
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.labelMedium,
            color = content.copy(alpha = 0.8f)
        )
        if (first != null && !first.failed) {
            LinearProgressIndicator(
                progress = { first.progress.toFloat().coerceIn(0f, 1f) },
                color = content,
                trackColor = content.copy(alpha = 0.3f),
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = Dimens.SpaceXS)
            )
        }
    }
}
