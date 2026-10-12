// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.navigation

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.ExperimentalSharedTransitionApi
import androidx.compose.animation.SharedTransitionLayout
import androidx.compose.animation.SharedTransitionScope
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavDestination.Companion.hierarchy
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavGraphBuilder
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.navigation
import androidx.navigation.compose.rememberNavController
import com.qtekfun.ultimatetunes.ui.album.AlbumRoute
import com.qtekfun.ultimatetunes.ui.artist.ArtistRoute
import com.qtekfun.ultimatetunes.ui.imports.ImportRoute
import com.qtekfun.ultimatetunes.ui.library.AlbumsRoute
import com.qtekfun.ultimatetunes.ui.library.ArtistsRoute
import com.qtekfun.ultimatetunes.ui.library.DownloadsRoute
import com.qtekfun.ultimatetunes.ui.library.FavouritesRoute
import com.qtekfun.ultimatetunes.ui.library.LibraryRoute
import com.qtekfun.ultimatetunes.ui.listennow.ListenNowRoute
import com.qtekfun.ultimatetunes.ui.lyrics.LyricsHooks
import com.qtekfun.ultimatetunes.ui.lyrics.LyricsViewModel
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import com.qtekfun.ultimatetunes.ui.player.FullPlayer
import com.qtekfun.ultimatetunes.ui.player.MiniPlayer
import com.qtekfun.ultimatetunes.ui.player.PlayerActions
import com.qtekfun.ultimatetunes.ui.player.PlayerUiState
import com.qtekfun.ultimatetunes.ui.player.PlayerViewModel
import com.qtekfun.ultimatetunes.ui.playlists.PlaylistRoute
import com.qtekfun.ultimatetunes.ui.playlists.PlaylistsRoute
import com.qtekfun.ultimatetunes.ui.radio.RadioRoute
import com.qtekfun.ultimatetunes.ui.radio.StationRoute
import com.qtekfun.ultimatetunes.ui.search.SearchRoute
import com.qtekfun.ultimatetunes.ui.settings.SettingsRoute

/** Key of the artwork shared between the mini and the full player. */
private const val SHARED_ARTWORK_KEY = "player.artwork"

/**
 * The app once connected: the four tabs with their bar, the mini player above it, and the full
 * player over everything, opened from the mini player with a shared-element transition of the
 * artwork (SPEC §5).
 */
@OptIn(ExperimentalSharedTransitionApi::class)
@Composable
fun MainScreen(
    playerViewModel: PlayerViewModel = hiltViewModel(),
    lyricsViewModel: LyricsViewModel = hiltViewModel()
) {
    val navController = rememberNavController()
    val player by playerViewModel.state.collectAsStateWithLifecycle()
    val lyrics = lyricsHooks(lyricsViewModel)
    var expanded by rememberSaveable { mutableStateOf(false) }
    val hasTrack = player.current != null
    val actions = remember(playerViewModel) { PlayerActions.of(playerViewModel) }
    BackHandler(enabled = expanded) { expanded = false }

    SharedTransitionLayout {
        Box(Modifier.fillMaxSize()) {
            Scaffold(
                containerColor = MaterialTheme.colorScheme.background,
                contentWindowInsets = WindowInsets(0),
                bottomBar = {
                    Column {
                        MiniPlayerBar(
                            visible = hasTrack && !expanded,
                            player = player,
                            actions = actions,
                            onOpen = { expanded = true }
                        )
                        TabBar(navController)
                    }
                }
            ) { padding ->
                TabsNavHost(
                    navController = navController,
                    contentPadding = PaddingValues(bottom = padding.calculateBottomPadding()),
                    onPlay = playerViewModel::play
                )
            }
            AnimatedVisibility(
                visible = hasTrack && expanded,
                enter = slideInVertically { it / 2 } + fadeIn(),
                exit = slideOutVertically { it / 2 } + fadeOut()
            ) {
                FullPlayer(
                    state = player,
                    actions = actions,
                    onCollapse = { expanded = false },
                    lyrics = lyrics,
                    artworkModifier = Modifier.sharedElement(
                        sharedContentState = rememberSharedContentState(SHARED_ARTWORK_KEY),
                        animatedVisibilityScope = this
                    )
                )
            }
        }
    }
}

/** The mini player above the tab bar, its artwork shared with the full player. */
@OptIn(ExperimentalSharedTransitionApi::class)
@Composable
private fun SharedTransitionScope.MiniPlayerBar(
    visible: Boolean,
    player: PlayerUiState,
    actions: PlayerActions,
    onOpen: () -> Unit
) {
    AnimatedVisibility(
        visible = visible,
        enter = fadeIn() + expandVertically(),
        exit = fadeOut() + shrinkVertically()
    ) {
        MiniPlayer(
            state = player,
            actions = actions,
            onOpen = onOpen,
            artworkModifier = Modifier.sharedElement(
                sharedContentState = rememberSharedContentState(SHARED_ARTWORK_KEY),
                animatedVisibilityScope = this
            )
        )
    }
}

/** The lyrics of the full player, from the activity-wide [LyricsViewModel]. */
@Composable
private fun lyricsHooks(viewModel: LyricsViewModel): LyricsHooks {
    val state by viewModel.state.collectAsStateWithLifecycle()
    return LyricsHooks(state = state, onShow = viewModel::show, onRetry = viewModel::retry)
}

@Composable
private fun TabBar(navController: NavHostController) {
    val backStackEntry by navController.currentBackStackEntryAsState()
    val destination = backStackEntry?.destination
    NavigationBar(containerColor = MaterialTheme.colorScheme.surfaceContainer) {
        Tab.entries.forEach { tab ->
            val selected = destination?.hierarchy?.any { it.route == tab.route } == true
            NavigationBarItem(
                selected = selected,
                onClick = {
                    navController.navigate(tab.route) {
                        popUpTo(navController.graph.findStartDestination().id) {
                            saveState = true
                        }
                        launchSingleTop = true
                        restoreState = true
                    }
                },
                icon = { Icon(painterResource(tab.icon), contentDescription = null) },
                label = { Text(stringResource(tab.label), maxLines = 1) },
                colors = NavigationBarItemDefaults.colors(
                    selectedIconColor = MaterialTheme.colorScheme.primary,
                    selectedTextColor = MaterialTheme.colorScheme.primary,
                    indicatorColor = Color.Transparent,
                    unselectedIconColor = MaterialTheme.colorScheme.onSurfaceVariant,
                    unselectedTextColor = MaterialTheme.colorScheme.onSurfaceVariant
                ),
                modifier = Modifier.testTag(tab.testTag)
            )
        }
    }
}

@Composable
private fun TabsNavHost(
    navController: NavHostController,
    contentPadding: PaddingValues,
    onPlay: (List<TrackTile>, Int) -> Unit
) {
    NavHost(
        navController = navController,
        startDestination = Tab.LISTEN_NOW.route
    ) {
        Tab.entries.forEach { tab ->
            navigation(route = tab.route, startDestination = tab.home) {
                composable(tab.home) {
                    TabHome(tab, contentPadding, rememberNavigator(tab, navController, onPlay))
                }
                details(tab, navController, contentPadding, onPlay)
                if (tab == Tab.LIBRARY) libraryPages(tab, navController, contentPadding, onPlay)
            }
        }
    }
}

/** The first screen of [tab]. */
@Composable
private fun TabHome(tab: Tab, contentPadding: PaddingValues, navigator: Navigator) {
    when (tab) {
        Tab.LISTEN_NOW -> ListenNowRoute(
            contentPadding = contentPadding,
            onPlay = navigator.play,
            onOpenStation = navigator.openStation,
            onOpenAlbum = navigator.openAlbum
        )

        Tab.RADIO -> RadioRoute(
            contentPadding = contentPadding,
            onOpenStation = navigator.openStation
        )

        Tab.LIBRARY -> LibraryRoute(contentPadding, navigator)

        Tab.SEARCH -> SearchRoute(contentPadding, navigator)
    }
}

/** Where screens inside [tab] go: always inside the same tab. */
@Composable
private fun rememberNavigator(
    tab: Tab,
    navController: NavHostController,
    onPlay: (List<TrackTile>, Int) -> Unit
): Navigator = remember(tab, navController, onPlay) {
    Navigator(
        back = { navController.popBackStack() },
        play = onPlay,
        openAlbum = { navController.navigate(tab.album(it)) },
        openArtist = { navController.navigate(tab.artist(it)) },
        openPlaylist = { navController.navigate(tab.playlist(it)) },
        openStation = { navController.navigate(tab.station(it)) },
        openPage = { navController.navigate(Tab.LIBRARY.page(it)) }
    )
}

/** Stations, albums, artists and playlists, inside [tab]. */
private fun NavGraphBuilder.details(
    tab: Tab,
    navController: NavHostController,
    contentPadding: PaddingValues,
    onPlay: (List<TrackTile>, Int) -> Unit
) {
    composable(tab.stationPattern) {
        StationRoute(
            contentPadding = contentPadding,
            onBack = { navController.popBackStack() },
            onPlay = onPlay
        )
    }
    composable(tab.albumPattern) {
        AlbumRoute(contentPadding, rememberNavigator(tab, navController, onPlay))
    }
    composable(tab.artistPattern) {
        ArtistRoute(contentPadding, rememberNavigator(tab, navController, onPlay))
    }
    composable(tab.playlistPattern) {
        PlaylistRoute(contentPadding, rememberNavigator(tab, navController, onPlay))
    }
}

/** The Library's pages, Import and Settings. */
private fun NavGraphBuilder.libraryPages(
    tab: Tab,
    navController: NavHostController,
    contentPadding: PaddingValues,
    onPlay: (List<TrackTile>, Int) -> Unit
) {
    LibraryPage.entries.forEach { page ->
        composable(tab.page(page)) {
            val navigator = rememberNavigator(tab, navController, onPlay)
            when (page) {
                LibraryPage.PLAYLISTS -> PlaylistsRoute(contentPadding, navigator)
                LibraryPage.ARTISTS -> ArtistsRoute(contentPadding, navigator)
                LibraryPage.ALBUMS -> AlbumsRoute(contentPadding, navigator)
                LibraryPage.FAVOURITES -> FavouritesRoute(contentPadding, navigator)
                LibraryPage.DOWNLOADS -> DownloadsRoute(contentPadding, navigator)
                LibraryPage.IMPORT -> ImportRoute(contentPadding, navigator)
                LibraryPage.SETTINGS -> SettingsRoute(contentPadding, navigator)
            }
        }
    }
}
