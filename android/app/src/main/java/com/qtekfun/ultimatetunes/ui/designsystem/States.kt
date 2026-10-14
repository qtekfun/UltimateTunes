// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.designsystem

import androidx.annotation.DrawableRes
import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.ui.localnet.LocalLocalNetworkHint
import com.qtekfun.ultimatetunes.ui.model.LoadError
import com.qtekfun.ultimatetunes.ui.theme.Dimens

/** The message shown for [error]. */
@StringRes
fun LoadError.messageRes(): Int = when (this) {
    LoadError.NETWORK -> R.string.error_network
    LoadError.UNAUTHORIZED -> R.string.error_unauthorized
    LoadError.NOT_CONFIGURED -> R.string.error_not_configured
    LoadError.SERVER -> R.string.error_server
}

/** A centred spinner, announced as "Loading". */
@Composable
fun LoadingState(modifier: Modifier = Modifier) {
    val label = stringResource(R.string.loading)
    Box(
        modifier = modifier
            .fillMaxWidth()
            .padding(vertical = Dimens.SpaceXXL * 2),
        contentAlignment = Alignment.Center
    ) {
        CircularProgressIndicator(
            modifier = Modifier.semantics { contentDescription = label }
        )
    }
}

/** A message with an icon and an optional action; errors are announced (live region). */
@Composable
fun MessageState(
    message: String,
    @DrawableRes icon: Int,
    modifier: Modifier = Modifier,
    actionLabel: String? = null,
    onAction: (() -> Unit)? = null
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = Dimens.ScreenMargin * 2, vertical = Dimens.SpaceXXL * 2),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(Dimens.SpaceL)
    ) {
        Icon(
            painter = painterResource(icon),
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(48.dp)
        )
        Text(
            text = message,
            style = MaterialTheme.typography.bodyLarge,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
            modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite }
        )
        if (actionLabel != null && onAction != null) {
            FilledTonalButton(onClick = onAction) { Text(actionLabel) }
        }
    }
}

/** Goes back to the Connect screen (provided by the app's root). */
val LocalReconnect = staticCompositionLocalOf<() -> Unit> { {} }

/**
 * A load error. A refused key or a missing server offer "Connect Again" (back to the Connect
 * screen, never a dead end); anything else "Try Again".
 */
@Composable
fun ErrorState(error: LoadError, onRetry: () -> Unit, modifier: Modifier = Modifier) {
    val needsConnect = error == LoadError.UNAUTHORIZED || error == LoadError.NOT_CONFIGURED
    val reconnect = LocalReconnect.current
    val localNetwork = LocalLocalNetworkHint.current
    // A network error while Android blocks the local network is that block, not a flaky server.
    val blockedByAndroid = error == LoadError.NETWORK && localNetwork.blocked
    MessageState(
        message = stringResource(
            if (blockedByAndroid) R.string.error_local_network else error.messageRes()
        ),
        icon = R.drawable.ic_cloud,
        actionLabel = stringResource(
            when {
                blockedByAndroid -> R.string.local_network_allow
                needsConnect -> R.string.connect_again
                else -> R.string.retry
            }
        ),
        onAction = when {
            blockedByAndroid -> localNetwork.onFix
            needsConnect -> reconnect
            else -> onRetry
        },
        modifier = modifier
    )
}

/**
 * Shows [error] once in [hostState] (a failed action such as a favourite or a rename), then calls
 * [onShown] so the view model forgets it.
 */
@Composable
fun MessageEffect(
    error: LoadError?,
    hostState: androidx.compose.material3.SnackbarHostState,
    onShown: () -> Unit
) {
    val message = error?.let { stringResource(it.messageRes()) }
    androidx.compose.runtime.LaunchedEffect(message) {
        if (message != null) {
            hostState.showSnackbar(message)
            onShown()
        }
    }
}
