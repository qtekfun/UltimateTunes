// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.buildlogic

import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.params.ParameterizedTest
import org.junit.jupiter.params.provider.ValueSource

class ForbiddenDependenciesTest {
    @ParameterizedTest
    @ValueSource(
        strings = [
            "com.google.android.gms:play-services-base",
            "com.google.android.play:review",
            "com.google.firebase:firebase-analytics",
            "com.crashlytics.sdk.android:crashlytics",
            "io.fabric.sdk.android:fabric",
            "io.sentry:sentry-android",
            "ch.acra:acra-core",
            "com.bugsnag:bugsnag-android",
            "com.datadoghq:dd-sdk-android-rum",
            "com.newrelic.agent.android:android-agent",
            "com.mixpanel.android:mixpanel-android",
            "com.posthog:posthog-android",
            "com.segment.analytics.kotlin:android",
            "com.rollbar:rollbar-android",
            "io.opentelemetry:opentelemetry-sdk"
        ]
    )
    fun `banned groups and their subgroups are forbidden`(module: String) {
        assertTrue(isForbidden(module))
    }

    @ParameterizedTest
    @ValueSource(
        strings = [
            "androidx.media3:media3-exoplayer",
            "com.squareup.okhttp3:okhttp",
            "io.fabric8:kubernetes-client",
            "com.google.android.material:material",
            "com.google.dagger:hilt-android"
        ]
    )
    fun `look-alike groups are allowed`(module: String) {
        assertFalse(isForbidden(module))
    }
}
