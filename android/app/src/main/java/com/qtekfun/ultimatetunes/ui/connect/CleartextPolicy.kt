// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.connect

/**
 * Whether plain `http://` may be used for a host. On a device it is the app's network security
 * config (HTTPS only; debug builds also allow the emulator's host), see `ui.di.ConnectModule`.
 */
fun interface CleartextPolicy {
    fun isPermitted(host: String): Boolean
}
