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
 * Keeps the connection across restarts (SPEC §7): restores the saved server and key at start, off
 * the main thread (the Connect screen may show for that moment), then saves every configuration
 * the Connect screen confirmed (never one still being checked) and forgets it on "Disconnect".
 */
class ConnectionPersistence(
    private val source: InMemoryServerConfigSource,
    private val gate: ConnectionGate,
    private val vault: ServerConfigVault,
    private val scope: CoroutineScope,
    private val io: CoroutineDispatcher
) {
    /**
     * Restores the saved configuration (unless one is set already) off the main thread, then saves
     * confirmed changes from then on. Restoring first keeps the initial "no configuration" from
     * erasing the saved one.
     */
    fun start() {
        scope.launch {
            val saved = withContext(io) { vault.load() }
            if (saved != null && source.config.value == null) source.set(saved)
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
            } catch (
                @Suppress("TooGenericExceptionCaught") ignored: RuntimeException
            ) {
                // Keystore providers also throw ProviderException and friends: same as above.
            }
        }
    }

    private data class Saved(val config: ServerConfig?)
}

/**
 * The playback side's work at app start; `UltimateTunesApp.onCreate` calls [onAppCreate] (see the
 * PR notes: that file belongs to another task). The Keystore work runs off the main thread.
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
        ConnectionPersistence(source, gate, vault, scope, Dispatchers.IO).start()
    }

    private companion object {
        const val KEY_ALIAS = "ut-server-config"
    }
}
