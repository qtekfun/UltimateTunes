// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.demo

import com.qtekfun.ultimatetunes.ui.connect.DemoServer
import dagger.Binds
import dagger.Module
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent

/** Debug builds bind the demo server, which turns on the Connect screen's demo button. */
@Module
@InstallIn(SingletonComponent::class)
interface DemoModule {
    @Binds
    fun demoServer(server: LocalDemoServer): DemoServer
}
