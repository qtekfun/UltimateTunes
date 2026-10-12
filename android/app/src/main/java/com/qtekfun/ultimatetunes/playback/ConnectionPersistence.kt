// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.playback

import android.content.Context
import com.qtekfun.ultimatetunes.core.api.InMemoryServerConfigSource
import com.qtekfun.ultimatetunes.core.api.ServerConfig
import com.qtekfun.ultimatetunes.ui.connect.ConnectionGate
import dagger.hilt.android.qualifiers.ApplicationContext
import java.io.File
import java.io.IOException
import java.security.GeneralSecurityException
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Keeps the connection across restarts (SPEC §7): restores the saved server and key before the
 * first screen decides between Connect and the app, then saves every configuration the Connect
 * screen confirmed (never one still being checked) and forgets it on "Disconnect".
 */
class ConnectionPersistence(
    private val source: InMemoryServerConfigSource,
    private val gate: ConnectionGate,
    private val vault: ServerConfigVault,
    private val scope: CoroutineScope,
    private val io: CoroutineDispatcher
) {
    /** Restores the saved configuration if none is set yet; call once, at app start. */
    fun restore() {
        if (source.config.value == null) vault.load()?.let(source::set)
    }

    /** Saves confirmed changes from now on. */
    fun start() {
        scope.launch {
            combine(source.config, gate.needsConnect) { config, needsConnect ->
                Saved(config).takeIf { config == null || !needsConnect }
            }
                .filterNotNull()
                .distinctUntilChanged()
                .collect { save(it.config) }
        }
    }

    private suspend fun save(config: ServerConfig?) {
        withContext(io) {
            try {
                vault.save(config)
            } catch (ignored: IOException) {
                // Not saved: the app asks to connect again after the next restart.
            } catch (ignored: GeneralSecurityException) {
                // Keystore unavailable: same as above, and the key never touches the disk.
            }
        }
    }

    private data class Saved(val config: ServerConfig?)
}

/**
 * The playback side's work at app start; `UltimateTunesApp.onCreate` calls [onAppCreate] (see the
 * PR notes: that file belongs to another task).
 */
@Singleton
class PlaybackStartup @Inject constructor(
    @param:ApplicationContext private val context: Context,
    private val source: InMemoryServerConfigSource,
    private val gate: ConnectionGate
) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)

    fun onAppCreate() {
        val vault = ServerConfigVault(
            File(context.noBackupFilesDir, "server_config.bin"),
            KeystoreSecretBox(KEY_ALIAS)
        )
        ConnectionPersistence(source, gate, vault, scope, Dispatchers.IO).apply {
            restore()
            start()
        }
    }

    private companion object {
        const val KEY_ALIAS = "ut-server-config"
    }
}
