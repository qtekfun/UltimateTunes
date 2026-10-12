// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.buildlogic

import com.android.build.api.dsl.ApplicationExtension
import org.gradle.api.Plugin
import org.gradle.api.Project
import org.gradle.kotlin.dsl.configure

/** `ut.android.application`: the app module, with Compose and the shared quality gates. */
class AndroidApplicationConventionPlugin : Plugin<Project> {
    override fun apply(target: Project) {
        with(target) {
            pluginManager.apply("com.android.application")
            pluginManager.apply("org.jetbrains.kotlin.plugin.compose")

            extensions.configure<ApplicationExtension> {
                configureAndroid(this)
                defaultConfig.targetSdk = TARGET_SDK
                buildFeatures.compose = true

                // Reproducible builds (F-Droid): no Google-encrypted dependency blob in the APK.
                dependenciesInfo.apply {
                    includeInApk = false
                    includeInBundle = false
                }

                androidResources.generateLocaleConfig = true
            }

            configureQuality()

            // The UI tests only run on a device (never in `check`), but they must always compile.
            tasks.named("check") { dependsOn("compileDebugAndroidTestSources") }
        }
    }
}
