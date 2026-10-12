// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.imports

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.core.api.ErrorKind
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.model.Import
import com.qtekfun.ultimatetunes.core.api.model.ImportFileFormat
import com.qtekfun.ultimatetunes.core.api.model.ImportId
import com.qtekfun.ultimatetunes.core.api.model.ImportItemState
import com.qtekfun.ultimatetunes.core.api.model.ImportSource
import com.qtekfun.ultimatetunes.core.api.model.ImportState
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import com.qtekfun.ultimatetunes.ui.model.loadStateOf
import com.qtekfun.ultimatetunes.ui.model.toTile
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** Why an import could not start or be followed, as the Import screen explains it. */
enum class ImportError {
    /** A Spotify link: v1 imports Spotify playlists from an exported file (SPEC §11, T03d). */
    SPOTIFY_URL,

    /** Not a YouTube Music or YouTube playlist link. */
    UNSUPPORTED_URL,

    /** Over 1 MiB or 5000 rows. */
    FILE_TOO_LARGE,

    /** The file could not be read in the chosen format. */
    INVALID_FILE,

    /** The server has this kind of import turned off. */
    DISABLED,

    RATE_LIMITED,
    NETWORK,
    UNAUTHORIZED,
    SERVER
}

/** A file chosen with the system picker: its name and content (at most [ImportViewModel.MAX_FILE_BYTES]). */
class PickedFile(val name: String, val content: ByteArray) {
    val sizeBytes: Int get() = content.size
}

/** One source track of the match report. */
data class ImportRow(
    val position: Int,
    val title: String,
    val artist: String?,
    val state: ImportItemState,
    /** What it matched, when it did. */
    val match: TrackTile?
)

/** An import and its progress, ready to show. */
data class ImportProgress(
    val id: ImportId,
    val name: String?,
    val source: ImportSource,
    val state: ImportState,
    val progress: Double,
    val total: Int,
    val matched: Int,
    val notFound: Int,
    val playlistId: PlaylistId?,
    val rows: List<ImportRow>
) {
    val inProgress: Boolean
        get() = state == ImportState.QUEUED || state == ImportState.READING ||
            state == ImportState.MATCHING
}

/** What the Import screen shows. */
data class ImportUiState(
    val url: String = "",
    val name: String = "",
    val file: PickedFile? = null,
    val format: ImportFileFormat = ImportFileFormat.CSV,
    val submitting: Boolean = false,
    val error: ImportError? = null,
    /** The import being followed (just started, or opened from the history). */
    val current: ImportProgress? = null,
    val history: LoadState<List<ImportProgress>> = LoadState.Loading
) {
    val canImportUrl: Boolean get() = !submitting && url.isNotBlank()
    val canImportFile: Boolean get() = !submitting && file != null
}

/**
 * Playlist import (RF-08): a YouTube Music or YouTube playlist link, or an exported file (generic
 * CSV, Exportify CSV, Spotify data-export JSON) chosen with the system picker. The import runs on
 * the server; this follows its progress (`GET /ut/v1/imports/{id}`) until the match report is
 * ready and the playlist exists.
 */
@Suppress("TooManyFunctions") // One function per action of the Import screen.
@HiltViewModel
class ImportViewModel @Inject constructor(private val api: TunesApi) : ViewModel() {
    private val mutableState = MutableStateFlow(ImportUiState())
    val state: StateFlow<ImportUiState> = mutableState.asStateFlow()

    private var watching: Job? = null
    private var historyJob: Job? = null

    init {
        loadHistory()
    }

    fun onUrlChange(value: String) {
        mutableState.update { it.copy(url = value, error = null) }
    }

    fun onNameChange(value: String) {
        mutableState.update { it.copy(name = value) }
    }

    /**
     * A file from the picker, or null when it could not be read; too large ones are refused here,
     * before any upload.
     */
    fun onFilePicked(file: PickedFile?) {
        if (file == null) {
            mutableState.update { it.copy(file = null, error = ImportError.INVALID_FILE) }
            return
        }
        if (file.sizeBytes > MAX_FILE_BYTES) {
            mutableState.update { it.copy(file = null, error = ImportError.FILE_TOO_LARGE) }
            return
        }
        mutableState.update {
            it.copy(file = file, format = guessFormat(file.name, file.content), error = null)
        }
    }

    fun onFormatChange(format: ImportFileFormat) {
        mutableState.update { it.copy(format = format) }
    }

    fun importUrl() {
        val state = mutableState.value
        if (!state.canImportUrl) return
        val url = state.url.trim()
        if (SPOTIFY_HOST.containsMatchIn(url)) {
            mutableState.update { it.copy(error = ImportError.SPOTIFY_URL) }
            return
        }
        start(fromFile = false) { api.createImport(url, state.name.trim().ifEmpty { null }) }
    }

    fun importFile() {
        val state = mutableState.value
        val file = state.file ?: return
        if (!state.canImportFile) return
        start(fromFile = true) {
            api.createFileImport(
                content = file.content,
                fileName = file.name,
                format = state.format,
                name = state.name.trim().ifEmpty { null }
            )
        }
    }

    /** Follows an earlier import from the history (its match report). */
    fun open(id: ImportId) {
        mutableState.update { it.copy(error = null) }
        watch(id)
    }

    /** Closes the import being followed. */
    fun closeCurrent() {
        watching?.cancel()
        mutableState.update { it.copy(current = null) }
    }

    fun loadHistory() {
        if (historyJob?.isActive == true) return
        historyJob = viewModelScope.launch {
            val history = loadStateOf(api.imports(limit = HISTORY_SIZE)) { list ->
                list.map { it.toProgress(api) }
            }
            mutableState.update { it.copy(history = history) }
        }
    }

    private fun start(fromFile: Boolean, call: suspend () -> TunesResult<Import>) {
        mutableState.update { it.copy(submitting = true, error = null) }
        viewModelScope.launch {
            when (val result = call()) {
                is TunesResult.Success -> {
                    mutableState.update {
                        it.copy(
                            submitting = false,
                            url = "",
                            name = "",
                            file = null,
                            current = result.value.toProgress(api)
                        )
                    }
                    loadHistory()
                    if (result.value.toProgress(api).inProgress) {
                        watch(
                            result.value.id,
                            initialDelay = true
                        )
                    }
                }

                is TunesResult.Failure -> mutableState.update {
                    it.copy(submitting = false, error = errorOf(result, fromFile))
                }
            }
        }
    }

    private fun watch(id: ImportId, initialDelay: Boolean = false) {
        watching?.cancel()
        watching = viewModelScope.launch {
            if (initialDelay) delay(POLL_MS)
            while (true) {
                when (val result = api.import(id)) {
                    is TunesResult.Success -> {
                        val progress = result.value.toProgress(api)
                        mutableState.update { it.copy(current = progress) }
                        if (!progress.inProgress) {
                            loadHistory()
                            return@launch
                        }
                    }

                    is TunesResult.Failure -> {
                        mutableState.update { it.copy(error = errorOf(result, fromFile = false)) }
                        return@launch
                    }
                }
                delay(POLL_MS)
            }
        }
    }

    companion object {
        /** The server's limit for uploaded playlist files (SPEC §11, T02). */
        const val MAX_FILE_BYTES = 1024 * 1024

        /** How often a running import is checked. */
        const val POLL_MS = 1_500L

        /** Imports listed under "Recent Imports". */
        const val HISTORY_SIZE = 20

        private val SPOTIFY_HOST =
            Regex("""(^|[/.])spotify\.(com|link)(/|$)""", RegexOption.IGNORE_CASE)

        /** Some editors start UTF-8 files with it. */
        private const val BYTE_ORDER_MARK = '\uFEFF'

        /** Bytes read to guess a file's format. */
        private const val SNIFF_BYTES = 4096

        /**
         * The format of a picked file, guessed from its name and first line: JSON is a Spotify
         * data export; a CSV with Exportify's columns ("Track URI", "Artist Name(s)") is
         * Exportify; any other CSV is the generic one. The user can still change it.
         */
        fun guessFormat(fileName: String, content: ByteArray): ImportFileFormat {
            val head = content.copyOf(minOf(content.size, SNIFF_BYTES)).decodeToString()
                .trimStart(BYTE_ORDER_MARK, ' ', '\n', '\r', '\t')
            val header = head.lineSequence().firstOrNull().orEmpty().lowercase()
            return when {
                fileName.lowercase().endsWith(".json") || head.startsWith("{") ||
                    head.startsWith("[") -> ImportFileFormat.SPOTIFY_JSON

                "track uri" in header || "artist name(s)" in header ->
                    ImportFileFormat.EXPORTIFY_CSV

                else -> ImportFileFormat.CSV
            }
        }

        /** How a failed call is explained; [fromFile] tells a bad file from a bad link. */
        fun errorOf(failure: TunesResult.Failure, fromFile: Boolean): ImportError = when (failure) {
            is TunesResult.ApiError -> when (failure.error.kind) {
                ErrorKind.UNSUPPORTED_URL -> ImportError.UNSUPPORTED_URL

                ErrorKind.PAYLOAD_TOO_LARGE -> ImportError.FILE_TOO_LARGE

                ErrorKind.INVALID_PARAMETER, ErrorKind.MISSING_PARAMETER ->
                    if (fromFile) ImportError.INVALID_FILE else ImportError.UNSUPPORTED_URL

                ErrorKind.FEATURE_DISABLED -> ImportError.DISABLED

                ErrorKind.RATE_LIMITED -> ImportError.RATE_LIMITED

                else -> ImportError.SERVER
            }

            is TunesResult.NetworkError -> ImportError.NETWORK

            is TunesResult.Unauthorized, TunesResult.NotConfigured -> ImportError.UNAUTHORIZED

            is TunesResult.ProtocolError -> ImportError.SERVER
        }
    }
}

/** [this] import as the screen shows it, matches as tiles. */
internal fun Import.toProgress(api: TunesApi) = ImportProgress(
    id = id,
    name = name,
    source = source,
    state = state,
    progress = progress,
    total = total,
    matched = matched,
    notFound = notFound,
    playlistId = playlistId,
    rows = items.map { item ->
        ImportRow(
            position = item.position,
            title = item.sourceTitle,
            artist = item.sourceArtist,
            state = item.state,
            match = item.track?.toTile(api)
        )
    }
)
