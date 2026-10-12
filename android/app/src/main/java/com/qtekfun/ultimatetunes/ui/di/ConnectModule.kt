// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.di

import android.security.NetworkSecurityPolicy
import com.qtekfun.ultimatetunes.ui.connect.CleartextPolicy
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent

@Module
@InstallIn(SingletonComponent::class)
object ConnectModule {
    /** Cleartext rules straight from the network security config, so the two never disagree. */
    @Provides
    fun cleartextPolicy(): CleartextPolicy = CleartextPolicy { host ->
        NetworkSecurityPolicy.getInstance().isCleartextTrafficPermitted(host)
    }
}
