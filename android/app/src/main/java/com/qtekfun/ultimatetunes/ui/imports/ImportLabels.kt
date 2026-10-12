// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.imports

import androidx.annotation.StringRes
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.core.api.model.ImportFileFormat
import com.qtekfun.ultimatetunes.core.api.model.ImportItemState
import com.qtekfun.ultimatetunes.core.api.model.ImportSource
import com.qtekfun.ultimatetunes.core.api.model.ImportState

/* How the Import screen names errors, formats, sources and states. */

@StringRes
internal fun ImportError.messageRes(): Int = when (this) {
    ImportError.SPOTIFY_URL -> R.string.import_error_spotify_url
    ImportError.UNSUPPORTED_URL -> R.string.import_error_unsupported_url
    ImportError.FILE_TOO_LARGE -> R.string.import_error_too_large
    ImportError.INVALID_FILE -> R.string.import_error_invalid_file
    ImportError.DISABLED -> R.string.import_error_disabled
    ImportError.RATE_LIMITED -> R.string.import_error_rate_limited
    ImportError.NETWORK -> R.string.error_network
    ImportError.UNAUTHORIZED -> R.string.error_unauthorized
    ImportError.SERVER -> R.string.error_server
}

@StringRes
internal fun ImportFileFormat.labelRes(): Int = when (this) {
    ImportFileFormat.CSV -> R.string.import_format_csv
    ImportFileFormat.EXPORTIFY_CSV -> R.string.import_format_exportify
    ImportFileFormat.SPOTIFY_JSON -> R.string.import_format_spotify_json
}

@StringRes
internal fun ImportSource.labelRes(): Int = when (this) {
    ImportSource.YTMUSIC -> R.string.import_source_ytmusic
    ImportSource.CSV -> R.string.import_format_csv
    ImportSource.EXPORTIFY_CSV -> R.string.import_format_exportify
    ImportSource.SPOTIFY_JSON -> R.string.import_format_spotify_json
}

@StringRes
internal fun ImportState.labelRes(): Int = when (this) {
    ImportState.QUEUED -> R.string.import_state_queued
    ImportState.READING -> R.string.import_state_reading
    ImportState.MATCHING -> R.string.import_state_matching
    ImportState.DONE -> R.string.import_state_done
    ImportState.FAILED -> R.string.import_state_failed
}

@StringRes
internal fun ImportItemState.labelRes(): Int = when (this) {
    ImportItemState.PENDING -> R.string.import_item_pending
    ImportItemState.MATCHED -> R.string.import_item_matched
    ImportItemState.NOT_FOUND -> R.string.import_item_not_found
    ImportItemState.FAILED -> R.string.import_item_failed
}
