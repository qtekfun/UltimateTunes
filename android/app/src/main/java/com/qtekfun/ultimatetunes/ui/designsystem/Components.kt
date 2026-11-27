// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.designsystem

import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.ui.actions.LocalTrackMenu
import com.qtekfun.ultimatetunes.ui.model.AlbumTile
import com.qtekfun.ultimatetunes.ui.model.StationTile
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import com.qtekfun.ultimatetunes.ui.theme.Dimens

/** A bold section title ("Recently Played"), marked as a heading for TalkBack. */
@Composable
fun SectionHeader(title: String, modifier: Modifier = Modifier) {
    Text(
        text = title,
        style = MaterialTheme.typography.titleLarge,
        color = MaterialTheme.colorScheme.onBackground,
        modifier = modifier
            .fillMaxWidth()
            .padding(
                start = Dimens.ScreenMargin,
                end = Dimens.ScreenMargin,
                top = Dimens.SpaceL,
                bottom = Dimens.SpaceM
            )
            .semantics { heading() }
    )
}

/** A horizontal shelf of [items] under the screen margins (keyed by position: items may repeat). */
@Composable
fun <T> Shelf(items: List<T>, modifier: Modifier = Modifier, itemContent: @Composable (T) -> Unit) {
    LazyRow(
        modifier = modifier.fillMaxWidth(),
        contentPadding = PaddingValues(horizontal = Dimens.ScreenMargin),
        horizontalArrangement = Arrangement.spacedBy(Dimens.SpaceM)
    ) {
        items(items) { itemContent(it) }
    }
}

/**
 * An album: square rounded artwork, title and artist below. Clickable only when [onClick] is
 * given; TalkBack reads it as one item.
 */
@Composable
fun AlbumCard(album: AlbumTile, modifier: Modifier = Modifier, onClick: (() -> Unit)? = null) {
    val available = LocalAvailability.current.canPlayAlbum(album.id)
    val description = availabilityDescription(
        stringResource(R.string.album_description, album.title, album.artist),
        available
    )
    Column(
        modifier = modifier
            .availableOrDimmed(available)
            .clip(Dimens.ArtworkShape)
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
            .clearAndSetSemantics { contentDescription = description }
    ) {
        Artwork(
            url = album.coverUrl,
            placeholderKey = album.id.value,
            modifier = Modifier.fillMaxWidth().aspectRatio(1f)
        )
        Spacer(Modifier.padding(top = Dimens.SpaceS))
        Text(
            text = album.title,
            style = MaterialTheme.typography.titleSmall,
            color = MaterialTheme.colorScheme.onBackground,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis
        )
        Text(
            text = album.artist,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis
        )
    }
}

/** An album of fixed width for a [Shelf]. */
@Composable
fun ShelfAlbumCard(album: AlbumTile, onClick: (() -> Unit)? = null) {
    AlbumCard(album = album, onClick = onClick, modifier = Modifier.width(Dimens.ShelfTile))
}

/**
 * A song as a fixed-width card for a [Shelf] (recommendations, charts): square rounded artwork,
 * title and artist below, the cloud marking one not in the library yet. TalkBack reads it as one
 * item, the note included.
 */
@Composable
fun ShelfTrackCard(track: TrackTile, onClick: () -> Unit, modifier: Modifier = Modifier) {
    val available = LocalAvailability.current.canPlay(track.id)
    val description = availabilityDescription(
        stringResource(R.string.track_description, track.title, track.artist),
        available
    )
    val external = stringResource(R.string.not_in_library)
    Column(
        modifier = modifier
            .width(Dimens.ShelfTile)
            .availableOrDimmed(available)
            .clip(Dimens.ArtworkShape)
            .clickable(onClick = onClick)
            .clearAndSetSemantics {
                contentDescription =
                    if (track.isExternal) "$description, $external" else description
            }
    ) {
        Artwork(
            url = track.coverUrl,
            placeholderKey = track.id.value,
            modifier = Modifier.fillMaxWidth().aspectRatio(1f)
        )
        Spacer(Modifier.padding(top = Dimens.SpaceS))
        Text(
            text = track.title,
            style = MaterialTheme.typography.titleSmall,
            color = MaterialTheme.colorScheme.onBackground,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis
        )
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (track.isExternal) {
                Icon(
                    painter = painterResource(R.drawable.ic_cloud),
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier
                        .size(14.dp)
                        .padding(end = Dimens.SpaceXS)
                )
            }
            Text(
                text = track.artist,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
        }
    }
}

/**
 * A radio station in a [Shelf]: round artwork of the shelves' size with the name below. A station
 * needs the server, so it is [available] only with a connection.
 */
@Composable
fun StationCard(
    station: StationTile,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    available: Boolean = true
) {
    val description = availabilityDescription(
        stringResource(R.string.station_description, station.title),
        available
    )
    Column(
        modifier = modifier
            .width(Dimens.ShelfTile)
            .availableOrDimmed(available)
            .clip(Dimens.ArtworkShape)
            .clickable(onClick = onClick)
            .clearAndSetSemantics { contentDescription = description },
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Artwork(
            url = station.coverUrl,
            placeholderKey = station.seedId.value,
            shape = CircleShape,
            modifier = Modifier.fillMaxWidth().aspectRatio(1f)
        )
        Spacer(Modifier.padding(top = Dimens.SpaceS))
        Text(
            text = station.title,
            style = MaterialTheme.typography.titleSmall,
            color = MaterialTheme.colorScheme.onBackground,
            textAlign = TextAlign.Center,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis
        )
    }
}

/**
 * A song row: artwork, title, artist (and "not in library yet" for external songs), an optional
 * trailing slot and the overflow button of the song menu. Dimmed when it cannot play now. At
 * least [Dimens.MinRowHeight] tall, growing with the font scale.
 */
@Composable
fun TrackRow(
    track: TrackTile,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    showDivider: Boolean = true,
    trailing: @Composable (() -> Unit)? = null
) {
    val available = LocalAvailability.current.canPlay(track.id)
    val description = availabilityDescription(
        stringResource(R.string.track_description, track.title, track.artist),
        available
    )
    val external = stringResource(R.string.not_in_library)
    val menu = LocalTrackMenu.current
    Column(modifier = modifier.fillMaxWidth()) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Row(
                modifier = Modifier
                    .weight(1f)
                    .heightIn(min = Dimens.MinRowHeight)
                    .combinedClickable(
                        onClick = onClick,
                        onLongClickLabel = stringResource(R.string.menu_actions_for, track.title),
                        onLongClick = { menu(track) }
                    )
                    .semantics(mergeDescendants = true) {
                        contentDescription =
                            if (track.isExternal) "$description, $external" else description
                    }
                    .availableOrDimmed(available)
                    .padding(start = Dimens.ScreenMargin)
                    .padding(vertical = Dimens.SpaceS),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Artwork(
                    url = track.coverUrl,
                    placeholderKey = track.id.value,
                    shape = Dimens.SmallArtworkShape,
                    modifier = Modifier.size(Dimens.RowArtwork)
                )
                TrackText(
                    track,
                    Modifier
                        .weight(1f)
                        .padding(horizontal = Dimens.SpaceM)
                )
            }
            trailing?.invoke()
            OverflowButton(track.title, onClick = { menu(track) })
        }
        if (showDivider) {
            HorizontalDivider(
                modifier = Modifier.padding(
                    start = Dimens.ScreenMargin + Dimens.RowArtwork + Dimens.SpaceM
                ),
                color = MaterialTheme.colorScheme.outlineVariant
            )
        }
    }
}

/** Title and artist of a song; a cloud marks one not in the library yet. */
@Composable
private fun TrackText(track: TrackTile, modifier: Modifier = Modifier) {
    Column(modifier = modifier) {
        Text(
            text = track.title,
            style = MaterialTheme.typography.bodyLarge,
            color = MaterialTheme.colorScheme.onBackground,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis
        )
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (track.isExternal) {
                Icon(
                    painter = painterResource(R.drawable.ic_cloud),
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier
                        .size(14.dp)
                        .padding(end = Dimens.SpaceXS)
                )
            }
            Text(
                text = track.artist,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
        }
    }
}

/** A list row leading to more ([onClick]): artwork, title, subtitle and a chevron. */
@Composable
fun NavigationRow(
    title: String,
    subtitle: String?,
    artworkUrl: String?,
    placeholderKey: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    contentDescription: String = title
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .heightIn(min = Dimens.MinRowHeight)
            .clickable(onClick = onClick)
            .clearAndSetSemantics { this.contentDescription = contentDescription }
            .padding(horizontal = Dimens.ScreenMargin, vertical = Dimens.SpaceS),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Artwork(
            url = artworkUrl,
            placeholderKey = placeholderKey,
            shape = Dimens.SmallArtworkShape,
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
            subtitle?.let {
                Text(
                    text = it,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }
        }
        Icon(
            painter = painterResource(R.drawable.ic_chevron_right),
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}

/** The visible way into the menu of [title], at the end of its row. */
@Composable
fun OverflowButton(title: String, onClick: () -> Unit, modifier: Modifier = Modifier) {
    IconButton(onClick = onClick, modifier = modifier.padding(end = Dimens.SpaceS)) {
        Icon(
            painter = painterResource(R.drawable.ic_more),
            contentDescription = stringResource(R.string.menu_actions_for, title),
            tint = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}
