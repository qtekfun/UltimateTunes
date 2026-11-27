// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.session

import com.qtekfun.ultimatetunes.core.api.model.SongId

/** What can play from the phone, as the player asks when a song does not load (RF-12). */
interface PhonePlayback {
    /** True when nothing else can play: no connection, or offline mode. */
    fun onlyPhone(): Boolean

    /** What is on the phone now. */
    suspend fun songs(): PhoneLookup
}

/** One look at the songs on the phone. */
fun interface PhoneLookup {
    /**
     * The id [id] plays under from the phone (a `yt:` song may be kept under the library id it
     * got), or null when it cannot play from the phone.
     */
    fun phoneId(id: SongId): SongId?
}
