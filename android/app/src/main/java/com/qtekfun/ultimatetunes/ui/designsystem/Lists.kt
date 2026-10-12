// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.designsystem

import androidx.annotation.DrawableRes
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Button
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.ui.model.AlbumTile
import com.qtekfun.ultimatetunes.ui.model.ArtistTile
import com.qtekfun.ultimatetunes.ui.theme.Dimens

/** Columns of the album grids. */
const val GRID_COLUMNS = 2

/**
 * A row of a mixed list (search results, favourites): artwork, title, a subtitle and, for an item
 * only on YouTube Music, the cloud and "Not in library yet". TalkBack reads it as one item.
 */
@Composable
fun ItemRow(
    title: String,
    artworkUrl: String?,
    placeholderKey: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    subtitle: String? = null,
    isExternal: Boolean = false,
    artworkShape: Shape = Dimens.SmallArtworkShape,
    showDivider: Boolean = true
) {
    val external = stringResource(R.string.not_in_library)
    val description = listOfNotNull(title, subtitle, external.takeIf { isExternal })
        .joinToString(", ")
    Column(modifier = modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(min = Dimens.MinRowHeight)
                .clickable(onClick = onClick)
                .clearAndSetSemantics { contentDescription = description }
                .padding(horizontal = Dimens.ScreenMargin, vertical = Dimens.SpaceS),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Artwork(
                url = artworkUrl,
                placeholderKey = placeholderKey,
                shape = artworkShape,
                modifier = Modifier.size(Dimens.RowArtwork)
            )
            Column(
                modifier = Modifier
                    .weight(1f)
                    .padding(horizontal = Dimens.SpaceM)
            ) {
                Text(
                    text = title,
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onBackground,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                ItemSubtitle(subtitle, if (isExternal) external else null)
            }
            Icon(
                painter = painterResource(R.drawable.ic_chevron_right),
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
        if (showDivider) RowDivider()
    }
}

@Composable
private fun ItemSubtitle(subtitle: String?, externalLabel: String?) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        if (externalLabel != null) {
            Icon(
                painter = painterResource(R.drawable.ic_cloud),
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier
                    .size(14.dp)
                    .padding(end = Dimens.SpaceXS)
            )
        }
        val text = listOfNotNull(subtitle, externalLabel).joinToString(" · ")
        if (text.isNotEmpty()) {
            Text(
                text = text,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
        }
    }
}

/** The divider under a list row, aligned with the text. */
@Composable
fun RowDivider() {
    HorizontalDivider(
        modifier = Modifier.padding(
            start = Dimens.ScreenMargin + Dimens.RowArtwork + Dimens.SpaceM
        ),
        color = MaterialTheme.colorScheme.outlineVariant
    )
}

/** An artist row: round artwork and the name. */
@Composable
fun ArtistRow(
    artist: ArtistTile,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    subtitle: String? = null,
    showDivider: Boolean = true
) {
    ItemRow(
        title = artist.name,
        subtitle = subtitle,
        artworkUrl = artist.coverUrl,
        placeholderKey = artist.id.value,
        isExternal = artist.isExternal,
        onClick = onClick,
        artworkShape = CircleShape,
        showDivider = showDivider,
        modifier = modifier
    )
}

/** A Library menu row ("Playlists", "Artists"…): an icon in the accent colour and a chevron. */
@Composable
fun MenuRow(
    title: String,
    @DrawableRes icon: Int,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    Column(modifier = modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(min = Dimens.MinRowHeight)
                .clickable(onClick = onClick)
                .semantics(mergeDescendants = true) {}
                .padding(horizontal = Dimens.ScreenMargin, vertical = Dimens.SpaceM),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Icon(
                painter = painterResource(icon),
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(28.dp)
            )
            Text(
                text = title,
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onBackground,
                modifier = Modifier
                    .weight(1f)
                    .padding(horizontal = Dimens.SpaceL)
            )
            Icon(
                painter = painterResource(R.drawable.ic_chevron_right),
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
        HorizontalDivider(
            modifier = Modifier.padding(start = Dimens.ScreenMargin + 28.dp + Dimens.SpaceL),
            color = MaterialTheme.colorScheme.outlineVariant
        )
    }
}

/** Albums in a grid of large rounded artwork, inside a screen's list. */
fun LazyListScope.albumGrid(
    albums: List<AlbumTile>,
    keyPrefix: String,
    onOpen: (AlbumTile) -> Unit
) {
    val rows = albums.chunked(GRID_COLUMNS)
    itemsIndexed(rows, key = { i, _ -> "$keyPrefix-$i" }) { _, row ->
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = Dimens.ScreenMargin)
                .padding(bottom = Dimens.SpaceL),
            horizontalArrangement = Arrangement.spacedBy(Dimens.SpaceM)
        ) {
            row.forEach { album ->
                AlbumCard(album, onClick = { onOpen(album) }, modifier = Modifier.weight(1f))
            }
            repeat(GRID_COLUMNS - row.size) { Spacer(Modifier.weight(1f)) }
        }
    }
}

/** "Play" and "Shuffle", side by side, under an album's or a playlist's header. */
@Composable
fun PlayShuffleButtons(
    onPlay: () -> Unit,
    onShuffle: () -> Unit,
    modifier: Modifier = Modifier,
    playTag: String = PLAY_BUTTON_TAG
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = Dimens.ScreenMargin, vertical = Dimens.SpaceM),
        horizontalArrangement = Arrangement.spacedBy(Dimens.SpaceM)
    ) {
        Button(
            onClick = onPlay,
            shape = Dimens.CardShape,
            modifier = Modifier
                .weight(1f)
                .heightIn(min = 48.dp)
                .testTag(playTag)
        ) {
            Icon(
                painter = painterResource(R.drawable.ic_play),
                contentDescription = null,
                modifier = Modifier.padding(end = Dimens.SpaceS)
            )
            Text(stringResource(R.string.play))
        }
        FilledTonalButton(
            onClick = onShuffle,
            shape = Dimens.CardShape,
            modifier = Modifier
                .weight(1f)
                .heightIn(min = 48.dp)
        ) {
            Icon(
                painter = painterResource(R.drawable.ic_shuffle),
                contentDescription = null,
                modifier = Modifier.padding(end = Dimens.SpaceS)
            )
            Text(stringResource(R.string.shuffle))
        }
    }
}

/** Test tag of the "Play" button of albums and playlists. */
const val PLAY_BUTTON_TAG = "detail.play"
