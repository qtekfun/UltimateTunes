// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.offline

import java.io.File
import java.io.IOException
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.emitAll
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json

/** Where the [OfflineSelection] is kept. */
interface OfflineSelectionStore {
    val selection: Flow<OfflineSelection>

    /** Changes the selection atomically. */
    suspend fun update(transform: (OfflineSelection) -> OfflineSelection)
}

/**
 * [OfflineSelectionStore] as one JSON file, replaced atomically (written aside, then renamed).
 * Changes are serialised by a mutex; the file is read once, on first use.
 */
class FileOfflineSelection(
    private val file: File,
    private val io: CoroutineDispatcher = Dispatchers.IO
) : OfflineSelectionStore {
    private val mutex = Mutex()
    private val state = MutableStateFlow<OfflineSelection?>(null)

    override val selection: Flow<OfflineSelection> = flowOfLoaded()

    override suspend fun update(transform: (OfflineSelection) -> OfflineSelection) {
        mutex.withLock {
            val next = transform(loaded())
            withContext(io) { write(next) }
            state.value = next
        }
    }

    private fun flowOfLoaded(): Flow<OfflineSelection> = flow {
        mutex.withLock { loaded() }
        emitAll(state.filterNotNull())
    }

    /** The selection, read from the file the first time. Call with the mutex held. */
    private suspend fun loaded(): OfflineSelection =
        state.value ?: withContext(io) { read() }.also { state.value = it }

    private fun read(): OfflineSelection = try {
        if (file.exists()) {
            JSON.decodeFromString<OfflineSelection>(
                file.readText()
            )
        } else {
            OfflineSelection()
        }
    } catch (ignored: IOException) {
        OfflineSelection()
    } catch (ignored: IllegalArgumentException) {
        // Unreadable (SerializationException is one): start over rather than crash.
        OfflineSelection()
    }

    private fun write(selection: OfflineSelection) {
        file.parentFile?.mkdirs()
        val temp = File(file.parentFile, file.name + ".tmp")
        temp.writeText(JSON.encodeToString(selection))
        if (!temp.renameTo(file)) throw IOException("Could not save the offline selection")
    }

    private companion object {
        val JSON = Json { ignoreUnknownKeys = true }
    }
}
