// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.di

import android.os.Build
import android.security.NetworkSecurityPolicy
import com.qtekfun.ultimatetunes.ui.connect.CleartextPolicy
import com.qtekfun.ultimatetunes.ui.connect.DeviceName
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

    /** A key created by signing in is named after the phone's model, e.g. "Pixel 9". */
    @Provides
    fun deviceName(): DeviceName = DeviceName { Build.MODEL.orEmpty() }
}
