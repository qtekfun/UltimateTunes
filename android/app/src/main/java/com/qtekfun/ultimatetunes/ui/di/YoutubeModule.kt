// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.di

import com.qtekfun.ultimatetunes.ui.youtube.CookieManagerSession
import com.qtekfun.ultimatetunes.ui.youtube.YoutubeWebSession
import dagger.Binds
import dagger.Module
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent

@Module
@InstallIn(SingletonComponent::class)
interface YoutubeModule {
    @Binds
    fun webSession(impl: CookieManagerSession): YoutubeWebSession
}
