// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.connect

import androidx.annotation.StringRes
import com.qtekfun.ultimatetunes.core.api.ServerConfig

/**
 * A way to try the app without a server. Only debug builds bind one (`src/debug`, a local server
 * on 127.0.0.1 with invented music); release builds have none, so the Connect screen shows no
 * demo button and the APK carries no demo code or data.
 */
interface DemoServer {
    /** The label of the Connect screen's demo button (a debug-only string). */
    @get:StringRes
    val labelRes: Int

    /**
     * Starts the demo server if needed and returns its address and key, which the Connect screen
     * then checks like any other server's; null when it could not start.
     */
    suspend fun start(): ServerConfig?
}
