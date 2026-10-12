// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.imports

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.core.api.model.ImportFileFormat
import com.qtekfun.ultimatetunes.core.api.model.ImportId
import com.qtekfun.ultimatetunes.core.api.model.ImportItemState
import com.qtekfun.ultimatetunes.core.api.model.ImportSource
import com.qtekfun.ultimatetunes.core.api.model.ImportState
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import com.qtekfun.ultimatetunes.ui.designsystem.ErrorState
import com.qtekfun.ultimatetunes.ui.designsystem.ItemRow
import com.qtekfun.ultimatetunes.ui.designsystem.LargeTitleScaffold
import com.qtekfun.ultimatetunes.ui.designsystem.LoadingState
import com.qtekfun.ultimatetunes.ui.designsystem.SectionHeader
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.navigation.Navigator
import com.qtekfun.ultimatetunes.ui.theme.Dimens
import com.qtekfun.ultimatetunes.ui.theme.UltimateTunesTheme
import kotlinx.coroutines.launch

/** Test tags of the Import screen. */
const val IMPORT_URL_TAG = "import.url"
const val IMPORT_URL_BUTTON_TAG = "import.urlButton"
const val IMPORT_PROGRESS_TAG = "import.progress"
const val IMPORT_INTRO_TAG = "import.intro"

/** What the Import screen can do. */
data class ImportActions(
    val onUrlChange: (String) -> Unit = {},
    val onNameChange: (String) -> Unit = {},
    val importUrl: () -> Unit = {},
    val pickFile: () -> Unit = {},
    val onFormatChange: (ImportFileFormat) -> Unit = {},
    val importFile: () -> Unit = {},
    val open: (ImportId) -> Unit = {},
    val closeCurrent: () -> Unit = {},
    val retryHistory: () -> Unit = {}
)

@Composable
fun ImportRoute(
    contentPadding: PaddingValues,
    navigator: Navigator,
    viewModel: ImportViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val resolver = LocalContext.current.contentResolver
    val scope = rememberCoroutineScope()
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) {
            scope.launch {
                val file = readPickedFile(resolver, uri)
                viewModel.onFilePicked(file)
            }
        }
    }
    ImportScreen(
        state = state,
        contentPadding = contentPadding,
        navigator = navigator,
        actions = ImportActions(
            onUrlChange = viewModel::onUrlChange,
            onNameChange = viewModel::onNameChange,
            importUrl = viewModel::importUrl,
            pickFile = { picker.launch(IMPORT_MIME_TYPES) },
            onFormatChange = viewModel::onFormatChange,
            importFile = viewModel::importFile,
            open = viewModel::open,
            closeCurrent = viewModel::closeCurrent,
            retryHistory = viewModel::loadHistory
        )
    )
}

/** Import a playlist (RF-08) from a YouTube Music link or an exported file. */
@Composable
fun ImportScreen(
    state: ImportUiState,
    contentPadding: PaddingValues,
    navigator: Navigator,
    actions: ImportActions
) {
    LargeTitleScaffold(
        title = stringResource(R.string.import_title),
        onBack = navigator.back
    ) { inner ->
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(
                top = inner.calculateTopPadding(),
                bottom = contentPadding.calculateBottomPadding() + Dimens.SpaceXL
            )
        ) {
            state.current?.let { current -> progress(current, navigator, actions) }
            item { ImportForm(state, actions) }
            history(state.history, actions)
        }
    }
}

@Composable
private fun ImportForm(state: ImportUiState, actions: ImportActions) {
    Column(
        modifier = Modifier.padding(horizontal = Dimens.ScreenMargin),
        verticalArrangement = Arrangement.spacedBy(Dimens.SpaceM)
    ) {
        Text(
            text = stringResource(
                if (state.anyImport) R.string.import_intro else R.string.import_all_disabled
            ),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.testTag(IMPORT_INTRO_TAG)
        )
        if (!state.anyImport) return@Column
        OutlinedTextField(
            value = state.name,
            onValueChange = actions.onNameChange,
            label = { Text(stringResource(R.string.import_name)) },
            singleLine = true,
            enabled = !state.submitting,
            modifier = Modifier.fillMaxWidth()
        )
        // Kinds the server has turned off are not offered (capabilities of /ut/v1/server).
        if (state.urlImport) LinkSection(state, actions)
        if (state.fileImport) FileSection(state, actions)
        state.error?.let { error ->
            Text(
                text = stringResource(error.messageRes()),
                color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite }
            )
        }
    }
}

@Composable
private fun LinkSection(state: ImportUiState, actions: ImportActions) {
    FormTitle(R.string.import_from_link)
    OutlinedTextField(
        value = state.url,
        onValueChange = actions.onUrlChange,
        label = { Text(stringResource(R.string.import_link)) },
        placeholder = { Text(stringResource(R.string.import_link_hint)) },
        singleLine = true,
        enabled = !state.submitting,
        keyboardOptions = KeyboardOptions(
            keyboardType = KeyboardType.Uri,
            imeAction = ImeAction.Go,
            autoCorrectEnabled = false
        ),
        modifier = Modifier.fillMaxWidth().testTag(IMPORT_URL_TAG)
    )
    Button(
        onClick = actions.importUrl,
        enabled = state.canImportUrl,
        shape = Dimens.PillShape,
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = 48.dp)
            .testTag(IMPORT_URL_BUTTON_TAG)
    ) { Text(stringResource(R.string.import_button)) }
}

@Composable
private fun FileSection(state: ImportUiState, actions: ImportActions) {
    FormTitle(R.string.import_from_file)
    Text(
        text = stringResource(R.string.import_file_help),
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant
    )
    OutlinedButton(
        onClick = actions.pickFile,
        enabled = !state.submitting,
        shape = Dimens.PillShape,
        modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp)
    ) {
        Icon(
            painter = painterResource(R.drawable.ic_upload),
            contentDescription = null,
            modifier = Modifier.padding(end = Dimens.SpaceS)
        )
        Text(state.file?.name ?: stringResource(R.string.import_choose_file))
    }
    state.file?.let { FileOptions(state, actions) }
}

@Composable
private fun FormTitle(@StringRes text: Int) {
    Text(
        text = stringResource(text),
        style = MaterialTheme.typography.titleMedium,
        color = MaterialTheme.colorScheme.onBackground,
        modifier = Modifier.padding(top = Dimens.SpaceM)
    )
}

@Composable
private fun FileOptions(state: ImportUiState, actions: ImportActions) {
    Column(modifier = Modifier.selectableGroup()) {
        ImportFileFormat.entries.forEach { format ->
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = 48.dp)
                    .selectable(
                        selected = state.format == format,
                        onClick = { actions.onFormatChange(format) },
                        role = Role.RadioButton
                    ),
                verticalAlignment = Alignment.CenterVertically
            ) {
                RadioButton(selected = state.format == format, onClick = null)
                Text(
                    text = stringResource(format.labelRes()),
                    style = MaterialTheme.typography.bodyLarge,
                    modifier = Modifier.padding(start = Dimens.SpaceM)
                )
            }
        }
    }
    Button(
        onClick = actions.importFile,
        enabled = state.canImportFile,
        shape = Dimens.PillShape,
        modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp)
    ) { Text(stringResource(R.string.import_file_button)) }
}

private fun LazyListScope.history(
    history: LoadState<List<ImportProgress>>,
    actions: ImportActions
) {
    item { SectionHeader(stringResource(R.string.import_recent)) }
    when (history) {
        LoadState.Loading -> item { LoadingState() }

        is LoadState.Failed -> item { ErrorState(history.error, actions.retryHistory) }

        is LoadState.Ready -> if (history.value.isEmpty()) {
            item {
                Text(
                    text = stringResource(R.string.import_none),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(horizontal = Dimens.ScreenMargin)
                )
            }
        } else {
            items(history.value, key = { "history-${it.id.value}" }) { entry ->
                ItemRow(
                    title = entry.name ?: stringResource(R.string.import_untitled),
                    subtitle = stringResource(entry.source.labelRes()) + " · " +
                        stringResource(entry.state.labelRes()),
                    artworkUrl = null,
                    placeholderKey = entry.id.value,
                    isExternal = false,
                    onClick = { actions.open(entry.id) }
                )
            }
        }
    }
}

@Preview(name = "Import, light", showBackground = true, heightDp = 1400)
@Preview(
    name = "Import, dark, large font",
    showBackground = true,
    heightDp = 1400,
    fontScale = 1.4f,
    uiMode = android.content.res.Configuration.UI_MODE_NIGHT_YES
)
@Composable
private fun ImportPreview() {
    UltimateTunesTheme {
        ImportScreen(
            state = ImportUiState(
                url = "https://music.youtube.com/playlist?list=PLexample",
                current = com.qtekfun.ultimatetunes.ui.preview.PreviewData.importDone,
                history = LoadState.Ready(
                    listOf(com.qtekfun.ultimatetunes.ui.preview.PreviewData.importDone)
                )
            ),
            contentPadding = PaddingValues(),
            navigator = Navigator(),
            actions = ImportActions()
        )
    }
}
