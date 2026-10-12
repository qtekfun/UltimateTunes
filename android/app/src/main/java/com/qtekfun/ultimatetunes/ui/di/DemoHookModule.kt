// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.di

import com.qtekfun.ultimatetunes.ui.connect.DemoServer
import dagger.BindsOptionalOf
import dagger.Module
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent

/** The [DemoServer] is optional: bound by debug builds only (`src/debug`), absent in release. */
@Module
@InstallIn(SingletonComponent::class)
interface DemoHookModule {
    @BindsOptionalOf
    fun demoServer(): DemoServer
}
