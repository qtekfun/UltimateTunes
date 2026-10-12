// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.qtekfun.ultimatetunes.ui.connect.ConnectRoute

/**
 * The app's root: the Connect screen when no server is configured, then the tabs ([MainScreen]).
 */
@Composable
fun AppRoot(viewModel: AppViewModel = hiltViewModel()) {
    val navController = rememberNavController()
    val start = remember { if (viewModel.isConfigured) AppRoutes.MAIN else AppRoutes.CONNECT }
    NavHost(navController = navController, startDestination = start) {
        composable(AppRoutes.CONNECT) {
            ConnectRoute(
                onConnected = {
                    navController.navigate(AppRoutes.MAIN) {
                        popUpTo(AppRoutes.CONNECT) { inclusive = true }
                    }
                }
            )
        }
        composable(AppRoutes.MAIN) { MainScreen() }
    }
}
