// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.api.fake

import mockwebserver3.RecordedRequest
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl

/** The parameters of a form POST, read like the query of a URL. */
fun RecordedRequest.form(): HttpUrl =
    "http://form.invalid/?${body?.utf8().orEmpty().replace("+", "%20")}".toHttpUrl()
