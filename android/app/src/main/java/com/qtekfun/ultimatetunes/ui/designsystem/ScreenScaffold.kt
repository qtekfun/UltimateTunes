// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.designsystem

import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.qtekfun.ultimatetunes.R

/** Opens Settings in the current tab; null where there is nowhere to open it (previews). */
val LocalOpenSettings = staticCompositionLocalOf<(() -> Unit)?> { null }

/** Test tag of the title (it scrolls sideways when it does not fit). */
const val TITLE_TAG = "screen.title"

/** Test tag of the header's Settings button. */
const val SETTINGS_BUTTON_TAG = "header.settings"

private val HEADER_HEIGHT = 64.dp
private val TITLE_SIZE = 28.sp

/** The header grows with the font scale up to this factor, so a large title is not cut. */
private const val MAX_HEADER_SCALE = 1.6f

/**
 * The one layout of every screen (SPEC §5): a header with the title, Back on detail pages, the
 * screen's own [actions] and the Settings button, with no empty space above the content.
 * [content] gets the padding below the header.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ScreenScaffold(
    title: String,
    modifier: Modifier = Modifier,
    onBack: (() -> Unit)? = null,
    actions: @Composable RowScope.() -> Unit = {},
    settingsButton: Boolean = true,
    snackbarHost: @Composable () -> Unit = {},
    content: @Composable (PaddingValues) -> Unit
) {
    val scrollBehavior = TopAppBarDefaults.pinnedScrollBehavior()
    val openSettings = LocalOpenSettings.current.takeIf { settingsButton }
    val scale = LocalDensity.current.fontScale.coerceIn(1f, MAX_HEADER_SCALE)
    Scaffold(
        modifier = modifier.nestedScroll(scrollBehavior.nestedScrollConnection),
        containerColor = MaterialTheme.colorScheme.background,
        contentWindowInsets = WindowInsets(0),
        snackbarHost = snackbarHost,
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        text = title,
                        style = MaterialTheme.typography.headlineSmall,
                        fontSize = TITLE_SIZE,
                        fontWeight = FontWeight.ExtraBold,
                        maxLines = 1,
                        modifier = Modifier
                            .basicMarquee(iterations = Int.MAX_VALUE)
                            .semantics { heading() }
                            .testTag(TITLE_TAG)
                    )
                },
                navigationIcon = {
                    if (onBack != null) {
                        IconButton(onClick = onBack) {
                            Icon(
                                painter = painterResource(R.drawable.ic_arrow_back),
                                contentDescription = stringResource(R.string.back),
                                tint = MaterialTheme.colorScheme.primary
                            )
                        }
                    }
                },
                actions = {
                    actions()
                    if (openSettings != null) SettingsButton(openSettings)
                },
                expandedHeight = HEADER_HEIGHT * scale,
                scrollBehavior = scrollBehavior,
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.background,
                    scrolledContainerColor = MaterialTheme.colorScheme.surfaceContainer
                )
            )
        },
        content = content
    )
}

@Composable
private fun SettingsButton(onClick: () -> Unit) {
    IconButton(onClick = onClick, modifier = Modifier.testTag(SETTINGS_BUTTON_TAG)) {
        Icon(
            painter = painterResource(R.drawable.ic_settings),
            contentDescription = stringResource(R.string.settings_title),
            tint = MaterialTheme.colorScheme.primary
        )
    }
}
