// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.di

import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.content.ContextCompat
import com.qtekfun.ultimatetunes.ui.localnet.HostResolver
import com.qtekfun.ultimatetunes.ui.localnet.LocalNetwork
import com.qtekfun.ultimatetunes.ui.localnet.LocalNetworkPermission
import com.qtekfun.ultimatetunes.ui.localnet.SystemHostResolver
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent

/** The system's side of the local network permission (Android 17+): the check and the resolver. */
@Module
@InstallIn(SingletonComponent::class)
object LocalNetworkModule {
    @Provides
    fun permission(@ApplicationContext context: Context): LocalNetworkPermission =
        LocalNetworkPermission {
            // Before Android 17 the permission does not exist and local access is free.
            Build.VERSION.SDK_INT < LocalNetwork.FIRST_SDK ||
                ContextCompat.checkSelfPermission(context, LocalNetwork.PERMISSION) ==
                PackageManager.PERMISSION_GRANTED
        }

    @Provides
    fun resolver(): HostResolver = SystemHostResolver()
}
