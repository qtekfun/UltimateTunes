// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.actions

import androidx.annotation.DrawableRes
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.ArtistId
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.ui.designsystem.Artwork
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import com.qtekfun.ultimatetunes.ui.theme.Dimens

/**
 * Opens the song menu of a track (long press on any song row, the full player's "more"); the app
 * provides it once, so every list gets the same menu (SPEC §5).
 */
val LocalTrackMenu = staticCompositionLocalOf<(TrackTile) -> Unit> { {} }

/**
 * What album and playlist screens offer for all their songs at once: add them to a playlist and
 * export them to the phone.
 */
@Immutable
data class CollectionActions(
    val addToPlaylist: (List<TrackTile>) -> Unit = {},
    val export: (List<TrackTile>) -> Unit = {}
)

/** The [CollectionActions] of the app. */
val LocalCollectionActions = staticCompositionLocalOf { CollectionActions() }

/** Test tags of the song menu. */
const val TRACK_MENU_TAG = "menu.track"

/** The entries of the song menu, in order. */
enum class TrackMenuItem(val tag: String) {
    PLAY_NEXT("menu.playNext"),
    PLAY_LAST("menu.playLast"),
    ADD_TO_PLAYLIST("menu.addToPlaylist"),
    FAVOURITE("menu.favourite"),
    DOWNLOAD("menu.download"),
    EXPORT("menu.export"),
    GO_TO_ALBUM("menu.album"),
    GO_TO_ARTIST("menu.artist"),
    START_STATION("menu.station")
}

/** What the song menu does; the menu closes itself after any of them. */
@Immutable
data class TrackMenuActions(
    val playNext: (TrackTile) -> Unit = {},
    val playLast: (TrackTile) -> Unit = {},
    val addToPlaylist: (TrackTile) -> Unit = {},
    val toggleFavourite: (TrackTile) -> Unit = {},
    val toggleDownload: (TrackTile) -> Unit = {},
    val export: (TrackTile) -> Unit = {},
    val openAlbum: (AlbumId) -> Unit = {},
    val openArtist: (ArtistId) -> Unit = {},
    val openStation: (SongId) -> Unit = {}
)

/** The song menu as a bottom sheet: the song on top, then its actions. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TrackMenuSheet(
    track: TrackTile,
    isFavourite: Boolean,
    isKeptOffline: Boolean,
    actions: TrackMenuActions,
    onDismiss: () -> Unit
) {
    val sheet = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = sheet,
        modifier = Modifier.testTag(TRACK_MENU_TAG)
    ) {
        Column(modifier = Modifier.verticalScroll(rememberScrollState())) {
            MenuHeader(track)
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            entries(track, isFavourite, isKeptOffline, actions).forEach { entry ->
                MenuEntryRow(entry) {
                    onDismiss()
                    entry.run()
                }
            }
            Spacer(Modifier.height(Dimens.SpaceL))
        }
    }
}

/** One entry of the menu. */
private class MenuEntry(
    val item: TrackMenuItem,
    @param:DrawableRes val icon: Int,
    val label: Int,
    val run: () -> Unit
)

private fun entries(
    track: TrackTile,
    isFavourite: Boolean,
    isKeptOffline: Boolean,
    actions: TrackMenuActions
): List<MenuEntry> = listOfNotNull(
    MenuEntry(TrackMenuItem.PLAY_NEXT, R.drawable.ic_queue, R.string.menu_play_next) {
        actions.playNext(track)
    },
    MenuEntry(TrackMenuItem.PLAY_LAST, R.drawable.ic_queue, R.string.menu_play_last) {
        actions.playLast(track)
    },
    MenuEntry(TrackMenuItem.ADD_TO_PLAYLIST, R.drawable.ic_add, R.string.menu_add_to_playlist) {
        actions.addToPlaylist(track)
    },
    MenuEntry(
        TrackMenuItem.FAVOURITE,
        if (isFavourite) R.drawable.ic_favorite else R.drawable.ic_favorite_border,
        if (isFavourite) R.string.favourite_remove else R.string.favourite_add
    ) { actions.toggleFavourite(track) },
    MenuEntry(
        TrackMenuItem.DOWNLOAD,
        if (isKeptOffline) R.drawable.ic_delete else R.drawable.ic_download,
        if (isKeptOffline) R.string.menu_remove_download else R.string.menu_download
    ) { actions.toggleDownload(track) },
    MenuEntry(TrackMenuItem.EXPORT, R.drawable.ic_upload, R.string.menu_export) {
        actions.export(track)
    },
    track.albumId?.let { album ->
        MenuEntry(TrackMenuItem.GO_TO_ALBUM, R.drawable.ic_album, R.string.menu_go_to_album) {
            actions.openAlbum(album)
        }
    },
    track.artistId?.let { artist ->
        MenuEntry(TrackMenuItem.GO_TO_ARTIST, R.drawable.ic_person, R.string.menu_go_to_artist) {
            actions.openArtist(artist)
        }
    },
    MenuEntry(TrackMenuItem.START_STATION, R.drawable.ic_radio, R.string.menu_start_station) {
        actions.openStation(track.id)
    }
)

@Composable
private fun MenuHeader(track: TrackTile) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = Dimens.ScreenMargin, vertical = Dimens.SpaceS),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Artwork(
            url = track.coverUrl,
            placeholderKey = track.id.value,
            shape = Dimens.SmallArtworkShape,
            modifier = Modifier.size(Dimens.RowArtwork)
        )
        Column(
            modifier = Modifier
                .weight(1f)
                .padding(horizontal = Dimens.SpaceM)
                .semantics(mergeDescendants = true) { heading() }
        ) {
            Text(
                text = track.title,
                style = MaterialTheme.typography.titleMedium,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
            Text(
                text = listOfNotNull(track.artist, track.album).joinToString(" · "),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
        }
    }
}

@Composable
private fun MenuEntryRow(entry: MenuEntry, onClick: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = Dimens.MinRowHeight)
            .clickable(role = Role.Button, onClick = onClick)
            .testTag(entry.item.tag)
            .padding(horizontal = Dimens.ScreenMargin, vertical = Dimens.SpaceS),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Icon(
            painter = painterResource(entry.icon),
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary
        )
        Text(
            text = stringResource(entry.label),
            style = MaterialTheme.typography.bodyLarge,
            modifier = Modifier.padding(start = Dimens.SpaceL)
        )
    }
}
