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
import androidx.compose.foundation.text.input.TextFieldState
import androidx.compose.foundation.text.input.TextObfuscationMode
import androidx.compose.foundation.text.input.setTextAndPlaceCursorAtEnd
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedSecureTextField
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
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
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.qtekfun.ultimatetunes.R
import com.qtekfun.ultimatetunes.ui.designsystem.placeholderBrush
import com.qtekfun.ultimatetunes.ui.theme.Dimens
import com.qtekfun.ultimatetunes.ui.theme.UltimateTunesTheme
import kotlinx.coroutines.flow.drop

/** Username, password and, once the server asks for it, the two-factor code. */
@Composable
internal fun PasswordFields(
    state: ConnectUiState,
    onUsernameChange: (String) -> Unit,
    onPasswordChange: (String) -> Unit,
    onCodeChange: (String) -> Unit,
    onConnect: () -> Unit
) {
    var passwordVisible by rememberSaveable { mutableStateOf(false) }
    val password = rememberSecretFieldState(state.password, onPasswordChange)
    val refused = state.error == ConnectError.WRONG_PASSWORD
    OutlinedTextField(
        value = state.username,
        onValueChange = onUsernameChange,
        label = { Text(stringResource(R.string.connect_username)) },
        singleLine = true,
        enabled = !state.checking,
        isError = refused,
        keyboardOptions = KeyboardOptions(
            keyboardType = KeyboardType.Text,
            imeAction = ImeAction.Next,
            autoCorrectEnabled = false
        ),
        modifier = Modifier.fillMaxWidth().testTag(CONNECT_USERNAME_TAG)
    )
    OutlinedSecureTextField(
        state = password,
        label = { Text(stringResource(R.string.connect_password)) },
        enabled = !state.checking,
        isError = refused,
        textObfuscationMode = obfuscation(passwordVisible),
        trailingIcon = {
            TextButton(onClick = { passwordVisible = !passwordVisible }) {
                Text(
                    stringResource(
                        if (passwordVisible) {
                            R.string.connect_hide_password
                        } else {
                            R.string.connect_show_password
                        }
                    )
                )
            }
        },
        keyboardOptions = KeyboardOptions(
            keyboardType = KeyboardType.Password,
            imeAction = if (state.needsCode) ImeAction.Next else ImeAction.Go,
            autoCorrectEnabled = false
        ),
        onKeyboardAction = { performDefaultAction ->
            if (state.needsCode) {
                performDefaultAction()
            } else if (state.canConnect) {
                onConnect()
            }
        },
        modifier = Modifier.fillMaxWidth().testTag(CONNECT_PASSWORD_TAG)
    )
    if (state.needsCode) CodeField(state, onCodeChange, onConnect)
}

@Composable
private fun CodeField(
    state: ConnectUiState,
    onCodeChange: (String) -> Unit,
    onConnect: () -> Unit
) {
    OutlinedTextField(
        value = state.code,
        onValueChange = onCodeChange,
        label = { Text(stringResource(R.string.connect_code)) },
        supportingText = { Text(stringResource(R.string.connect_code_help)) },
        singleLine = true,
        enabled = !state.checking,
        isError = state.error == ConnectError.WRONG_CODE,
        keyboardOptions = KeyboardOptions(
            keyboardType = KeyboardType.Ascii,
            imeAction = ImeAction.Go,
            autoCorrectEnabled = false
        ),
        keyboardActions = KeyboardActions(onGo = { if (state.canConnect) onConnect() }),
        modifier = Modifier
            .fillMaxWidth()
            .testTag(CONNECT_CODE_TAG)
            .semantics { liveRegion = LiveRegionMode.Polite }
    )
}

/** Shown in full or hidden: the secret is never revealed a character at a time. */
internal fun obfuscation(visible: Boolean): TextObfuscationMode =
    if (visible) TextObfuscationMode.Visible else TextObfuscationMode.Hidden

/**
 * The state of a password or key field holding [value]. Typing is reported to [onChange]; the
 * field only takes [value] back when it was emptied or filled from outside. Not saved with the
 * instance state, so the secret stays out of it.
 */
@Composable
internal fun rememberSecretFieldState(value: String, onChange: (String) -> Unit): TextFieldState {
    val field = remember { TextFieldState(value) }
    val report by rememberUpdatedState(onChange)
    LaunchedEffect(value) {
        val shown = field.text.toString()
        if (shown != value && (shown.isEmpty() || value.isEmpty())) {
            field.setTextAndPlaceCursorAtEnd(value)
        }
    }
    LaunchedEffect(field) {
        snapshotFlow { field.text.toString() }.drop(1).collect { report(it) }
    }
    return field
}
