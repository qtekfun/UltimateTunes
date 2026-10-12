// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.library

import androidx.annotation.DrawableRes
import androidx.annotation.StringRes
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.tooling.preview.Preview
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.ui.designsystem.ErrorState
import com.qtekfun.ultimatetunes.ui.designsystem.LargeTitleScaffold
import com.qtekfun.ultimatetunes.ui.designsystem.LoadingState
import com.qtekfun.ultimatetunes.ui.designsystem.MenuRow
import com.qtekfun.ultimatetunes.ui.designsystem.SectionHeader
import com.qtekfun.ultimatetunes.ui.designsystem.albumGrid
import com.qtekfun.ultimatetunes.ui.model.AlbumTile
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.navigation.LibraryPage
import com.qtekfun.ultimatetunes.ui.navigation.Navigator
import com.qtekfun.ultimatetunes.ui.preview.PreviewData
import com.qtekfun.ultimatetunes.ui.theme.Dimens
import com.qtekfun.ultimatetunes.ui.theme.UltimateTunesTheme

/** Test tag of a Library menu row, by page. */
fun libraryRowTag(page: LibraryPage): String = "library.${page.route}"

/** The Library menu, in order. */
private enum class LibraryEntry(
    val page: LibraryPage,
    @StringRes val label: Int,
    @DrawableRes val icon: Int
) {
    PLAYLISTS(LibraryPage.PLAYLISTS, R.string.library_playlists, R.drawable.ic_queue),
    ARTISTS(LibraryPage.ARTISTS, R.string.library_artists, R.drawable.ic_person),
    ALBUMS(LibraryPage.ALBUMS, R.string.library_albums, R.drawable.ic_album),
    FAVOURITES(LibraryPage.FAVOURITES, R.string.library_favourites, R.drawable.ic_favorite),
    DOWNLOADS(LibraryPage.DOWNLOADS, R.string.library_downloads, R.drawable.ic_download)
}

@Composable
fun LibraryRoute(
    contentPadding: PaddingValues,
    navigator: Navigator,
    viewModel: LibraryViewModel = hiltViewModel()
) {
    val recentlyAdded by viewModel.recentlyAdded.collectAsStateWithLifecycle()
    LibraryScreen(recentlyAdded, contentPadding, navigator, onRetry = viewModel::load)
}

/** The Library tab: its pages, Import and Settings in the bar, and the albums added last. */
@Composable
fun LibraryScreen(
    recentlyAdded: LoadState<List<AlbumTile>>,
    contentPadding: PaddingValues,
    navigator: Navigator,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier
) {
    LargeTitleScaffold(
        title = stringResource(R.string.tab_library),
        modifier = modifier,
        actions = {
            BarAction(R.drawable.ic_upload, R.string.import_title) {
                navigator.openPage(LibraryPage.IMPORT)
            }
            BarAction(R.drawable.ic_settings, R.string.settings_title) {
                navigator.openPage(LibraryPage.SETTINGS)
            }
        }
    ) { inner ->
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(
                top = inner.calculateTopPadding(),
                bottom = contentPadding.calculateBottomPadding() + Dimens.SpaceXL
            )
        ) {
            items(LibraryEntry.entries, key = { it.name }) { entry ->
                MenuRow(
                    title = stringResource(entry.label),
                    icon = entry.icon,
                    onClick = { navigator.openPage(entry.page) },
                    modifier = Modifier.testTag(libraryRowTag(entry.page))
                )
            }
            when (recentlyAdded) {
                LoadState.Loading -> item { LoadingState() }

                is LoadState.Failed -> item { ErrorState(recentlyAdded.error, onRetry) }

                is LoadState.Ready -> if (recentlyAdded.value.isNotEmpty()) {
                    item { SectionHeader(stringResource(R.string.listen_now_recently_added)) }
                    albumGrid(recentlyAdded.value, keyPrefix = "recent") {
                        navigator.openAlbum(it.id)
                    }
                }
            }
        }
    }
}

/** An icon button of a top bar, in the accent colour. */
@Composable
fun BarAction(@DrawableRes icon: Int, @StringRes label: Int, onClick: () -> Unit) {
    IconButton(onClick = onClick) {
        Icon(
            painter = painterResource(icon),
            contentDescription = stringResource(label),
            tint = MaterialTheme.colorScheme.primary
        )
    }
}

@Preview(name = "Library, light", showBackground = true, heightDp = 1100)
@Preview(
    name = "Library, dark, large font",
    showBackground = true,
    heightDp = 1100,
    fontScale = 1.5f,
    uiMode = android.content.res.Configuration.UI_MODE_NIGHT_YES
)
@Composable
private fun LibraryPreview() {
    UltimateTunesTheme {
        LibraryScreen(
            recentlyAdded = LoadState.Ready(PreviewData.albums),
            contentPadding = PaddingValues(),
            navigator = Navigator(),
            onRetry = {}
        )
    }
}
