// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.navigation

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.ExperimentalSharedTransitionApi
import androidx.compose.animation.SharedTransitionLayout
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
import com.qtekfun.ultimatetunes.ui.library.LibraryScreen
import com.qtekfun.ultimatetunes.ui.listennow.ListenNowRoute
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import com.qtekfun.ultimatetunes.ui.player.FullPlayer
import com.qtekfun.ultimatetunes.ui.player.MiniPlayer
import com.qtekfun.ultimatetunes.ui.player.PlayerActions
import com.qtekfun.ultimatetunes.ui.player.PlayerViewModel
import com.qtekfun.ultimatetunes.ui.radio.RadioRoute
import com.qtekfun.ultimatetunes.ui.radio.StationRoute
import com.qtekfun.ultimatetunes.ui.search.SearchScreen

/** Key of the artwork shared between the mini and the full player. */
private const val SHARED_ARTWORK_KEY = "player.artwork"

/**
 * The app once connected: the four tabs with their bar, the mini player above it, and the full
 * player over everything, opened from the mini player with a shared-element transition of the
 * artwork (SPEC §5).
 */
@OptIn(ExperimentalSharedTransitionApi::class)
@Composable
fun MainScreen(playerViewModel: PlayerViewModel = hiltViewModel()) {
    val navController = rememberNavController()
    val player by playerViewModel.state.collectAsStateWithLifecycle()
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
                        AnimatedVisibility(
                            visible = hasTrack && !expanded,
                            enter = fadeIn() + expandVertically(),
                            exit = fadeOut() + shrinkVertically()
                        ) {
                            MiniPlayer(
                                state = player,
                                actions = actions,
                                onOpen = { expanded = true },
                                artworkModifier = Modifier.sharedElement(
                                    sharedContentState = rememberSharedContentState(
                                        SHARED_ARTWORK_KEY
                                    ),
                                    animatedVisibilityScope = this
                                )
                            )
                        }
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
                    artworkModifier = Modifier.sharedElement(
                        sharedContentState = rememberSharedContentState(SHARED_ARTWORK_KEY),
                        animatedVisibilityScope = this
                    )
                )
            }
        }
    }
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
        navigation(route = Tab.LISTEN_NOW.route, startDestination = Tab.LISTEN_NOW.home) {
            composable(Tab.LISTEN_NOW.home) {
                ListenNowRoute(
                    contentPadding = contentPadding,
                    onPlay = onPlay,
                    onOpenStation = { navController.navigate(Tab.LISTEN_NOW.station(it)) }
                )
            }
            station(Tab.LISTEN_NOW, navController, contentPadding, onPlay)
        }
        navigation(route = Tab.RADIO.route, startDestination = Tab.RADIO.home) {
            composable(Tab.RADIO.home) {
                RadioRoute(
                    contentPadding = contentPadding,
                    onOpenStation = { navController.navigate(Tab.RADIO.station(it)) }
                )
            }
            station(Tab.RADIO, navController, contentPadding, onPlay)
        }
        navigation(route = Tab.LIBRARY.route, startDestination = Tab.LIBRARY.home) {
            composable(Tab.LIBRARY.home) { LibraryScreen(contentPadding) }
        }
        navigation(route = Tab.SEARCH.route, startDestination = Tab.SEARCH.home) {
            composable(Tab.SEARCH.home) { SearchScreen(contentPadding) }
        }
    }
}

private fun NavGraphBuilder.station(
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
}
