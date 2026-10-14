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
import com.qtekfun.ultimatetunes.ui.connect.ConnectLinkRoute
import com.qtekfun.ultimatetunes.ui.connect.ConnectRoute
import com.qtekfun.ultimatetunes.ui.designsystem.LocalReconnect
import com.qtekfun.ultimatetunes.ui.localnet.LocalLocalNetworkHint
import com.qtekfun.ultimatetunes.ui.localnet.LocalNetworkAccess
import com.qtekfun.ultimatetunes.ui.localnet.LocalNetworkHint
import com.qtekfun.ultimatetunes.ui.localnet.LocalNetworkViewModel

/**
 * The app's root: the Connect screen while no working server is configured, else the tabs
 * ([MainScreen]). Screens that hit a refused key offer "Connect Again" through [LocalReconnect].
 * A connect link (the admin panel's QR code) asks for confirmation over either of them.
 */
@Composable
fun AppRoot(
    viewModel: AppViewModel = hiltViewModel(),
    localNetwork: LocalNetworkViewModel = hiltViewModel()
) {
    val showConnect by viewModel.showConnect.collectAsStateWithLifecycle()
    val localNetworkState by localNetwork.state.collectAsStateWithLifecycle()
    val askNotifications by viewModel.askNotifications.collectAsStateWithLifecycle()
    Surface(color = MaterialTheme.colorScheme.background) {
        CompositionLocalProvider(
            LocalReconnect provides viewModel::reconnect,
            LocalLocalNetworkHint provides LocalNetworkHint(
                blocked = localNetworkState.blocked,
                onFix = localNetwork::reopen
            )
        ) {
            if (showConnect) {
                ConnectRoute()
            } else {
                MainScreen(
                    askNotifications = askNotifications,
                    onNotificationsAnswered = viewModel::onNotificationsAsked
                )
            }
            ConnectLinkRoute()
            LocalNetworkAccess(localNetwork, refreshKey = showConnect)
        }
    }
}
