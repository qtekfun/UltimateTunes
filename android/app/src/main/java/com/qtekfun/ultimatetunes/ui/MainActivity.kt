// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import coil3.ImageLoader
import coil3.compose.setSingletonImageLoaderFactory
import coil3.network.okhttp.OkHttpNetworkFetcherFactory
import coil3.request.crossfade
import com.qtekfun.ultimatetunes.core.api.di.TunesHttpClient
import com.qtekfun.ultimatetunes.ui.navigation.AppRoot
import com.qtekfun.ultimatetunes.ui.theme.UltimateTunesTheme
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject
import okhttp3.OkHttpClient

@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    /**
     * The authenticated client: cover URLs carry no key, this client adds it for the configured
     * server only (`TunesApi.coverArtUrl`).
     */
    @Inject
    @TunesHttpClient
    lateinit var httpClient: OkHttpClient

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            setSingletonImageLoaderFactory { context ->
                ImageLoader.Builder(context)
                    .components { add(OkHttpNetworkFetcherFactory(callFactory = { httpClient })) }
                    .crossfade(true)
                    .build()
            }
            UltimateTunesTheme {
                AppRoot()
            }
        }
    }
}
