// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.navigation

import androidx.lifecycle.ViewModel
import com.qtekfun.ultimatetunes.core.api.ServerConfigSource
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject

/** Whether the app starts on the Connect screen or on the tabs. */
@HiltViewModel
class AppViewModel @Inject constructor(private val configSource: ServerConfigSource) : ViewModel() {
    /** True when a server URL and key are already configured. */
    val isConfigured: Boolean get() = configSource.config.value != null
}
