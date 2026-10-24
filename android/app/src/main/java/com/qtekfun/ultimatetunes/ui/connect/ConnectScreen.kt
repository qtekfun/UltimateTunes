// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.connect

import androidx.annotation.StringRes
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.wrapContentWidth
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.ui.designsystem.placeholderBrush
import com.qtekfun.ultimatetunes.ui.theme.Dimens
import com.qtekfun.ultimatetunes.ui.theme.UltimateTunesTheme

/** Test tags of the Connect screen. */
const val CONNECT_SERVER_URL_TAG = "connect.serverUrl"
const val CONNECT_API_KEY_TAG = "connect.apiKey"
const val CONNECT_USERNAME_TAG = "connect.username"
const val CONNECT_PASSWORD_TAG = "connect.password"
const val CONNECT_CODE_TAG = "connect.code"
const val CONNECT_METHOD_PASSWORD_TAG = "connect.method.password"
const val CONNECT_METHOD_KEY_TAG = "connect.method.key"
const val CONNECT_BUTTON_TAG = "connect.button"
const val CONNECT_DEMO_TAG = "connect.demo"

/** The Connect screen with its view model; the root moves on once the key works. */
@Composable
fun ConnectRoute(viewModel: ConnectViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    ConnectScreen(
        state = state,
        onServerUrlChange = viewModel::onServerUrlChange,
        onApiKeyChange = viewModel::onApiKeyChange,
        onConnect = viewModel::connect,
        onMethodChange = viewModel::onMethodChange,
        onUsernameChange = viewModel::onUsernameChange,
        onPasswordChange = viewModel::onPasswordChange,
        onCodeChange = viewModel::onCodeChange,
        demoLabelRes = viewModel.demoLabelRes,
        onTryDemo = viewModel::tryDemo
    )
}

/** The message of each check failure, shared with the connect-link dialog. */
@StringRes
internal fun ConnectError.messageRes(): Int = when (this) {
    ConnectError.INVALID_URL -> R.string.connect_error_invalid_url
    ConnectError.INSECURE_URL -> R.string.connect_error_insecure_url
    ConnectError.INVALID_KEY -> R.string.connect_error_invalid_key
    ConnectError.UNREACHABLE -> R.string.connect_error_unreachable
    ConnectError.NOT_A_SERVER -> R.string.connect_error_not_a_server
    ConnectError.KEY_REFUSED -> R.string.connect_error_key_refused
    ConnectError.SERVER_ERROR -> R.string.connect_error_server
    ConnectError.WRONG_PASSWORD -> R.string.connect_error_wrong_password
    ConnectError.WRONG_CODE -> R.string.connect_error_wrong_code
    ConnectError.ACCOUNT_DISABLED -> R.string.connect_error_account_disabled
    ConnectError.TOO_MANY_TRIES -> R.string.connect_error_too_many_tries
    ConnectError.TWO_FACTOR_SETUP_REQUIRED -> R.string.connect_error_2fa_setup
}

/**
 * Server address with username and password or with an API key (RF-11), or how to use the admin
 * panel's QR code with the camera app.
 */
@Composable
@Suppress("LongParameterList") // One callback per field of the form.
fun ConnectScreen(
    state: ConnectUiState,
    onServerUrlChange: (String) -> Unit,
    onApiKeyChange: (String) -> Unit,
    onConnect: () -> Unit,
    modifier: Modifier = Modifier,
    onMethodChange: (ConnectMethod) -> Unit = {},
    onUsernameChange: (String) -> Unit = {},
    onPasswordChange: (String) -> Unit = {},
    onCodeChange: (String) -> Unit = {},
    @StringRes demoLabelRes: Int? = null,
    onTryDemo: () -> Unit = {}
) {
    // A Surface, not a plain Box: it sets the content colour, so text follows light and dark.
    Surface(modifier = modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
        Column(
            modifier = Modifier
                .safeDrawingPadding()
                .imePadding()
                .wrapContentWidth(Alignment.CenterHorizontally)
                .widthIn(max = 480.dp)
                .fillMaxWidth()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = Dimens.ScreenMargin, vertical = Dimens.SpaceXXL),
            verticalArrangement = Arrangement.spacedBy(Dimens.SpaceL),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            ConnectHeader()
            ServerUrlField(state, onServerUrlChange)
            MethodChoice(state, onMethodChange)
            when (state.method) {
                ConnectMethod.PASSWORD -> PasswordFields(
                    state,
                    onUsernameChange,
                    onPasswordChange,
                    onCodeChange,
                    onConnect
                )

                ConnectMethod.API_KEY -> ApiKeyField(state, onApiKeyChange, onConnect)
            }
            state.error?.let { error ->
                Text(
                    text = stringResource(error.messageRes()),
                    color = MaterialTheme.colorScheme.error,
                    style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier
                        .fillMaxWidth()
                        .semantics { liveRegion = LiveRegionMode.Polite }
                )
            }
            ConnectActions(state, onConnect)
            // Debug builds only: the demo server (src/debug); release builds pass no label.
            demoLabelRes?.let { label ->
                TextButton(
                    onClick = onTryDemo,
                    enabled = !state.checking,
                    modifier = Modifier.testTag(CONNECT_DEMO_TAG)
                ) {
                    Text(stringResource(label))
                }
            }
        }
    }
}

@Composable
private fun ConnectHeader() {
    Box(
        modifier = Modifier
            .size(88.dp)
            .clip(Dimens.CardShape)
            .background(placeholderBrush("UltimateTunes")),
        contentAlignment = Alignment.Center
    ) {
        Icon(
            painter = painterResource(R.drawable.ic_music_note),
            contentDescription = null,
            tint = Color.White,
            modifier = Modifier.size(48.dp)
        )
    }
    Text(
        text = stringResource(R.string.connect_title),
        style = MaterialTheme.typography.displaySmall,
        color = MaterialTheme.colorScheme.onBackground,
        textAlign = TextAlign.Center,
        modifier = Modifier.semantics { heading() }
    )
    Text(
        text = stringResource(R.string.app_tagline),
        style = MaterialTheme.typography.bodyLarge,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        textAlign = TextAlign.Center
    )
}

@Composable
private fun ServerUrlField(state: ConnectUiState, onServerUrlChange: (String) -> Unit) {
    OutlinedTextField(
        value = state.serverUrl,
        onValueChange = onServerUrlChange,
        label = { Text(stringResource(R.string.connect_server_url)) },
        placeholder = { Text(stringResource(R.string.connect_server_url_hint)) },
        singleLine = true,
        enabled = !state.checking,
        isError = state.error == ConnectError.INVALID_URL ||
            state.error == ConnectError.INSECURE_URL,
        keyboardOptions = KeyboardOptions(
            keyboardType = KeyboardType.Uri,
            imeAction = ImeAction.Next,
            autoCorrectEnabled = false
        ),
        modifier = Modifier.fillMaxWidth().testTag(CONNECT_SERVER_URL_TAG)
    )
}

@Composable
private fun MethodChoice(state: ConnectUiState, onMethodChange: (ConnectMethod) -> Unit) {
    val methods = listOf(
        Triple(
            ConnectMethod.PASSWORD,
            R.string.connect_method_password,
            CONNECT_METHOD_PASSWORD_TAG
        ),
        Triple(ConnectMethod.API_KEY, R.string.connect_method_key, CONNECT_METHOD_KEY_TAG)
    )
    SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
        methods.forEachIndexed { index, (method, label, tag) ->
            SegmentedButton(
                selected = state.method == method,
                onClick = { onMethodChange(method) },
                shape = SegmentedButtonDefaults.itemShape(index = index, count = methods.size),
                enabled = !state.checking,
                modifier = Modifier.testTag(tag)
            ) {
                Text(stringResource(label))
            }
        }
    }
}

@Composable
private fun ApiKeyField(
    state: ConnectUiState,
    onApiKeyChange: (String) -> Unit,
    onConnect: () -> Unit
) {
    var keyVisible by rememberSaveable { mutableStateOf(false) }
    OutlinedTextField(
        value = state.apiKey,
        onValueChange = onApiKeyChange,
        label = { Text(stringResource(R.string.connect_api_key)) },
        placeholder = { Text(stringResource(R.string.connect_api_key_hint)) },
        singleLine = true,
        enabled = !state.checking,
        isError = state.error == ConnectError.INVALID_KEY ||
            state.error == ConnectError.KEY_REFUSED,
        visualTransformation = if (keyVisible) {
            VisualTransformation.None
        } else {
            PasswordVisualTransformation()
        },
        trailingIcon = {
            TextButton(onClick = { keyVisible = !keyVisible }) {
                Text(
                    stringResource(
                        if (keyVisible) R.string.connect_hide_key else R.string.connect_show_key
                    )
                )
            }
        },
        keyboardOptions = KeyboardOptions(
            keyboardType = KeyboardType.Password,
            imeAction = ImeAction.Go,
            autoCorrectEnabled = false
        ),
        keyboardActions = KeyboardActions(onGo = { if (state.canConnect) onConnect() }),
        modifier = Modifier.fillMaxWidth().testTag(CONNECT_API_KEY_TAG)
    )
}

@Composable
private fun ConnectActions(state: ConnectUiState, onConnect: () -> Unit) {
    var qrInfoShown by rememberSaveable { mutableStateOf(false) }
    Button(
        onClick = onConnect,
        enabled = state.canConnect,
        shape = Dimens.PillShape,
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = 52.dp)
            .testTag(CONNECT_BUTTON_TAG)
    ) {
        if (state.checking) {
            CircularProgressIndicator(
                modifier = Modifier.size(20.dp),
                strokeWidth = 2.dp,
                color = MaterialTheme.colorScheme.onPrimary
            )
            Text(
                text = stringResource(R.string.connect_checking),
                modifier = Modifier.padding(start = Dimens.SpaceS)
            )
        } else {
            Text(stringResource(R.string.connect_button))
        }
    }
    // The admin panel's QR code is read by the phone's own camera app, which opens the
    // `ultimatetunes://connect` link (ConnectLinkViewModel): no camera library in the app.
    OutlinedButton(
        onClick = { qrInfoShown = true },
        shape = Dimens.PillShape,
        modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp)
    ) {
        Icon(
            painter = painterResource(R.drawable.ic_qr_code),
            contentDescription = null,
            modifier = Modifier.padding(end = Dimens.SpaceS)
        )
        Text(stringResource(R.string.connect_scan_qr))
    }
    if (qrInfoShown) {
        Text(
            text = stringResource(R.string.connect_qr_how),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite }
        )
    }
    Text(
        text = stringResource(
            when (state.method) {
                ConnectMethod.PASSWORD -> R.string.connect_help_password
                ConnectMethod.API_KEY -> R.string.connect_help
            }
        ),
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        textAlign = TextAlign.Center
    )
}

@Preview(name = "Connect, light", showBackground = true)
@Preview(
    name = "Connect, dark, large font",
    showBackground = true,
    fontScale = 1.5f,
    uiMode = android.content.res.Configuration.UI_MODE_NIGHT_YES
)
@Composable
private fun ConnectScreenPreview() {
    UltimateTunesTheme {
        ConnectScreen(
            state = ConnectUiState(
                serverUrl = "music.example.net",
                username = "alice",
                password = "example",
                needsCode = true,
                error = ConnectError.WRONG_CODE
            ),
            onServerUrlChange = {},
            onApiKeyChange = {},
            onConnect = {}
        )
    }
}
