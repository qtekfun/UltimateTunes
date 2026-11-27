// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.homescreen

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.ui.designsystem.Artwork
import com.qtekfun.ultimatetunes.ui.designsystem.ErrorState
import com.qtekfun.ultimatetunes.ui.designsystem.LoadingState
import com.qtekfun.ultimatetunes.ui.designsystem.LocalAvailability
import com.qtekfun.ultimatetunes.ui.designsystem.MenuRow
import com.qtekfun.ultimatetunes.ui.designsystem.MessageState
import com.qtekfun.ultimatetunes.ui.designsystem.PageRefresh
import com.qtekfun.ultimatetunes.ui.designsystem.RefreshBox
import com.qtekfun.ultimatetunes.ui.designsystem.ScreenScaffold
import com.qtekfun.ultimatetunes.ui.designsystem.SectionHeader
import com.qtekfun.ultimatetunes.ui.designsystem.Shelf
import com.qtekfun.ultimatetunes.ui.designsystem.ShelfAlbumCard
import com.qtekfun.ultimatetunes.ui.designsystem.ShelfTrackCard
import com.qtekfun.ultimatetunes.ui.designsystem.StationCard
import com.qtekfun.ultimatetunes.ui.designsystem.SyncProblemRow
import com.qtekfun.ultimatetunes.ui.designsystem.TrackRow
import com.qtekfun.ultimatetunes.ui.designsystem.availabilityDescription
import com.qtekfun.ultimatetunes.ui.designsystem.availableOrDimmed
import com.qtekfun.ultimatetunes.ui.designsystem.rememberScreenSnackbar
import com.qtekfun.ultimatetunes.ui.model.AlbumTile
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import com.qtekfun.ultimatetunes.ui.navigation.LibraryPage
import com.qtekfun.ultimatetunes.ui.navigation.Navigator
import com.qtekfun.ultimatetunes.ui.preview.PreviewData
import com.qtekfun.ultimatetunes.ui.theme.Dimens
import com.qtekfun.ultimatetunes.ui.theme.UltimateTunesTheme

/** Test tag of the favourites tile. */
const val HOME_FAVOURITES_TAG = "home.favourites"

private const val QUICK_COLUMNS = 2

/** The favourites and what was played last, two to a row. */
@Composable
internal fun QuickAccess(albums: List<AlbumTile>, navigator: Navigator) {
    val availability = LocalAvailability.current
    val shown = albums.filter { availability.showsAlbum(it.id) }
    // The favourites first; null stands for them.
    val tiles: List<AlbumTile?> = listOf<AlbumTile?>(null) + shown
    tiles.chunked(QUICK_COLUMNS).forEach { row ->
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = Dimens.ScreenMargin, vertical = Dimens.SpaceXS),
            horizontalArrangement = Arrangement.spacedBy(Dimens.SpaceS)
        ) {
            row.forEach { album ->
                if (album == null) {
                    FavouritesTile(
                        onClick = { navigator.openPage(LibraryPage.FAVOURITES) },
                        modifier = Modifier.weight(1f)
                    )
                } else {
                    QuickAlbumTile(
                        album = album,
                        onClick = { navigator.openAlbum(album.id) },
                        modifier = Modifier.weight(1f)
                    )
                }
            }
            repeat(QUICK_COLUMNS - row.size) { Spacer(Modifier.weight(1f)) }
        }
    }
}

@Composable
private fun QuickAlbumTile(album: AlbumTile, onClick: () -> Unit, modifier: Modifier) {
    val available = LocalAvailability.current.canPlayAlbum(album.id)
    val description = availabilityDescription(
        stringResource(R.string.album_description, album.title, album.artist),
        available
    )
    QuickTile(
        title = album.title,
        onClick = onClick,
        modifier = modifier
            .clearAndSetSemantics { contentDescription = description }
            .availableOrDimmed(available)
    ) {
        Artwork(
            url = album.coverUrl,
            placeholderKey = album.id.value,
            shape = Dimens.SmallArtworkShape,
            modifier = Modifier.size(Dimens.MinRowHeight)
        )
    }
}

@Composable
private fun FavouritesTile(onClick: () -> Unit, modifier: Modifier) {
    QuickTile(
        title = stringResource(R.string.library_favourites),
        onClick = onClick,
        modifier = modifier.testTag(HOME_FAVOURITES_TAG)
    ) {
        Box(
            modifier = Modifier
                .size(Dimens.MinRowHeight)
                .background(MaterialTheme.colorScheme.primaryContainer),
            contentAlignment = Alignment.Center
        ) {
            Icon(
                painter = painterResource(R.drawable.ic_favorite),
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onPrimaryContainer
            )
        }
    }
}

@Composable
private fun QuickTile(
    title: String,
    onClick: () -> Unit,
    modifier: Modifier,
    leading: @Composable () -> Unit
) {
    Row(
        // The click comes first, so clearing the semantics in [modifier] keeps it.
        modifier = Modifier
            .clip(Dimens.ArtworkShape)
            .clickable(onClick = onClick)
            .then(modifier)
            .background(MaterialTheme.colorScheme.surfaceContainer)
            .heightIn(min = Dimens.MinRowHeight),
        verticalAlignment = Alignment.CenterVertically
    ) {
        leading()
        Text(
            text = title,
            style = MaterialTheme.typography.titleSmall,
            color = MaterialTheme.colorScheme.onBackground,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.padding(horizontal = Dimens.SpaceS)
        )
    }
}
