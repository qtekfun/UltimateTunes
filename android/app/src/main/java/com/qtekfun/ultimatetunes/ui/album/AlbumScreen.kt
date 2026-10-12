// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.album

import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.ui.actions.CollectionMenuItems
import com.qtekfun.ultimatetunes.ui.actions.LocalTrackMenu
import com.qtekfun.ultimatetunes.ui.actions.OfflineNote
import com.qtekfun.ultimatetunes.ui.designsystem.Artwork
import com.qtekfun.ultimatetunes.ui.designsystem.ErrorState
import com.qtekfun.ultimatetunes.ui.designsystem.LargeTitleScaffold
import com.qtekfun.ultimatetunes.ui.designsystem.LoadingState
import com.qtekfun.ultimatetunes.ui.designsystem.MessageEffect
import com.qtekfun.ultimatetunes.ui.designsystem.PlayShuffleButtons
import com.qtekfun.ultimatetunes.ui.designsystem.rememberScreenSnackbar
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import com.qtekfun.ultimatetunes.ui.model.formatDuration
import com.qtekfun.ultimatetunes.ui.model.totalMinutes
import com.qtekfun.ultimatetunes.ui.navigation.Navigator
import com.qtekfun.ultimatetunes.ui.preview.PreviewData
import com.qtekfun.ultimatetunes.ui.theme.Dimens
import com.qtekfun.ultimatetunes.ui.theme.UltimateTunesTheme

/** Test tags of the album screen. */
const val ALBUM_LIST_TAG = "album.list"
const val ALBUM_MENU_TAG = "album.menu"

@Composable
fun AlbumRoute(
    contentPadding: PaddingValues,
    navigator: Navigator,
    viewModel: AlbumViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    AlbumScreen(
        state = state,
        contentPadding = contentPadding,
        navigator = navigator,
        onRetry = viewModel::load,
        onToggleFavourite = viewModel::toggleFavourite,
        onMessageShown = viewModel::dismissMessage,
        onToggleOffline = viewModel::toggleOffline
    )
}

/** An album: artwork, artist, Play and Shuffle, and its songs. */
@Composable
fun AlbumScreen(
    state: AlbumUiState,
    contentPadding: PaddingValues,
    navigator: Navigator,
    onRetry: () -> Unit,
    onToggleFavourite: () -> Unit,
    modifier: Modifier = Modifier,
    onMessageShown: () -> Unit = {},
    onToggleOffline: () -> Unit = {}
) {
    val content = (state.content as? LoadState.Ready)?.value
    val snackbar = rememberScreenSnackbar()
    MessageEffect(state.message, snackbar.state, onMessageShown)
    LargeTitleScaffold(
        title = content?.album?.title.orEmpty(),
        onBack = navigator.back,
        modifier = modifier,
        snackbarHost = snackbar.host,
        actions = {
            if (content != null && content.canFavourite) {
                FavouriteButton(content.isFavourite, onToggleFavourite)
            }
            if (content != null) AlbumMenu(content.tracks, state.isOffline, onToggleOffline)
        }
    ) { inner ->
        LazyColumn(
            modifier = Modifier.fillMaxSize().testTag(ALBUM_LIST_TAG),
            contentPadding = PaddingValues(
                top = inner.calculateTopPadding(),
                bottom = contentPadding.calculateBottomPadding() + Dimens.SpaceXL
            )
        ) {
            when (val load = state.content) {
                LoadState.Loading -> item { LoadingState() }

                is LoadState.Failed -> item { ErrorState(load.error, onRetry) }

                is LoadState.Ready -> {
                    val album = load.value
                    item { AlbumHeader(album, navigator, state.isOffline) }
                    itemsIndexed(album.tracks, key = { i, t -> "$i-${t.id.value}" }) { i, track ->
                        AlbumTrackRow(
                            track = track,
                            number = track.trackNumber ?: (i + 1),
                            onClick = { navigator.play(album.tracks, i) }
                        )
                    }
                    item { AlbumFooter(album) }
                }
            }
        }
    }
}

/** The heart of the top bar: filled when the album is a favourite. */
@Composable
fun FavouriteButton(isFavourite: Boolean, onToggle: () -> Unit) {
    IconButton(onClick = onToggle) {
        Icon(
            painter = painterResource(
                if (isFavourite) R.drawable.ic_favorite else R.drawable.ic_favorite_border
            ),
            contentDescription = stringResource(
                if (isFavourite) R.string.favourite_remove else R.string.favourite_add
            ),
            tint = MaterialTheme.colorScheme.primary
        )
    }
}

/** The album's menu: keep offline, add to a playlist, export. */
@Composable
private fun AlbumMenu(tracks: List<TrackTile>, isOffline: Boolean, onToggleOffline: () -> Unit) {
    var open by remember { mutableStateOf(false) }
    IconButton(onClick = { open = true }, modifier = Modifier.testTag(ALBUM_MENU_TAG)) {
        Icon(
            painter = painterResource(R.drawable.ic_more),
            contentDescription = stringResource(R.string.more_options),
            tint = MaterialTheme.colorScheme.primary
        )
    }
    DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
        CollectionMenuItems(tracks, isOffline, onToggleOffline, close = { open = false })
    }
}

@Composable
private fun AlbumHeader(album: AlbumContent, navigator: Navigator, isOffline: Boolean) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(Dimens.SpaceS)
    ) {
        Artwork(
            url = album.album.coverUrl,
            placeholderKey = album.album.id.value,
            shape = Dimens.CardShape,
            modifier = Modifier
                .fillMaxWidth(fraction = 0.72f)
                .widthIn(max = 300.dp)
                .aspectRatio(1f)
        )
        val artistId = album.artistId
        Text(
            text = album.album.artist,
            style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.primary,
            textAlign = TextAlign.Center,
            modifier = Modifier
                .padding(
                    top = Dimens.SpaceS,
                    start = Dimens.ScreenMargin,
                    end = Dimens.ScreenMargin
                )
                .then(
                    if (artistId != null) {
                        Modifier.clickable { navigator.openArtist(artistId) }
                    } else {
                        Modifier
                    }
                )
        )
        AlbumDetails(album)
        OfflineNote(isOffline)
        if (album.tracks.isNotEmpty()) {
            PlayShuffleButtons(
                onPlay = { navigator.play(album.tracks, 0) },
                onShuffle = { navigator.play(album.tracks.shuffled(), 0) }
            )
        }
    }
}

/** Genre and year, and for a YouTube Music album the note that it is not in the library yet. */
@Composable
private fun AlbumDetails(album: AlbumContent) {
    val details = listOfNotNull(album.genre, album.year?.toString()).joinToString(" · ")
    if (details.isNotEmpty()) {
        Text(
            text = details,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
    if (album.album.isExternal) {
        Text(
            text = stringResource(R.string.album_external),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
            modifier = Modifier.padding(horizontal = Dimens.ScreenMargin)
        )
    }
}

/** A song of an album: its number, title (with the cloud when external) and duration. */
@Composable
fun AlbumTrackRow(track: TrackTile, number: Int, onClick: () -> Unit) {
    val description = stringResource(R.string.track_description, track.title, track.artist) +
        if (track.isExternal) ", " + stringResource(R.string.not_in_library) else ""
    val menu = LocalTrackMenu.current
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = Dimens.MinRowHeight)
            .combinedClickable(
                onClick = onClick,
                onLongClickLabel = stringResource(R.string.menu_actions_for, track.title),
                onLongClick = { menu(track) }
            )
            .semantics(mergeDescendants = true) { contentDescription = description }
            .padding(horizontal = Dimens.ScreenMargin, vertical = Dimens.SpaceS),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(
            text = number.toString(),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.End,
            modifier = Modifier.widthIn(min = 28.dp)
        )
        Text(
            text = track.title,
            style = MaterialTheme.typography.bodyLarge,
            color = MaterialTheme.colorScheme.onBackground,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier
                .weight(1f)
                .padding(horizontal = Dimens.SpaceM)
        )
        if (track.isExternal) {
            Icon(
                painter = painterResource(R.drawable.ic_cloud),
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier
                    .padding(end = Dimens.SpaceS)
                    .size(16.dp)
            )
        }
        track.durationSec?.let {
            Text(
                text = formatDuration(it),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

@Composable
private fun AlbumFooter(album: AlbumContent) {
    val songs = pluralStringResource(R.plurals.song_count, album.tracks.size, album.tracks.size)
    val minutes = totalMinutes(album.durationSec)
    Text(
        text = songs + ", " + pluralStringResource(R.plurals.minute_count, minutes, minutes),
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.padding(horizontal = Dimens.ScreenMargin, vertical = Dimens.SpaceL)
    )
}

@Preview(name = "Album, light", showBackground = true, heightDp = 1100)
@Preview(
    name = "Album, dark, large font",
    showBackground = true,
    heightDp = 1100,
    fontScale = 1.5f,
    uiMode = android.content.res.Configuration.UI_MODE_NIGHT_YES
)
@Composable
private fun AlbumPreview() {
    UltimateTunesTheme {
        AlbumScreen(
            state = AlbumUiState(LoadState.Ready(PreviewData.album)),
            contentPadding = PaddingValues(),
            navigator = Navigator(),
            onRetry = {},
            onToggleFavourite = {}
        )
    }
}
