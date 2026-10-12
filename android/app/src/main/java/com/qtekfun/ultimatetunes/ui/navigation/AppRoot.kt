// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.navigation

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.qtekfun.ultimatetunes.ui.connect.ConnectRoute
import com.qtekfun.ultimatetunes.ui.designsystem.LocalReconnect

/**
 * The app's root: the Connect screen while no working server is configured, else the tabs
 * ([MainScreen]). Screens that hit a refused key offer "Connect Again" through [LocalReconnect].
 */
@Composable
fun AppRoot(viewModel: AppViewModel = hiltViewModel()) {
    val showConnect by viewModel.showConnect.collectAsStateWithLifecycle()
    Surface(color = MaterialTheme.colorScheme.background) {
        CompositionLocalProvider(LocalReconnect provides viewModel::reconnect) {
            if (showConnect) ConnectRoute() else MainScreen()
        }
    }
}
