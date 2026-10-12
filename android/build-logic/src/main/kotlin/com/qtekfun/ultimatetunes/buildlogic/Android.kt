// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.buildlogic

import com.android.build.api.dsl.CommonExtension
import org.gradle.api.JavaVersion
import org.gradle.api.Project
import org.gradle.kotlin.dsl.configure
import org.jetbrains.kotlin.gradle.dsl.JvmTarget
import org.jetbrains.kotlin.gradle.dsl.KotlinAndroidProjectExtension

internal const val COMPILE_SDK = 37
internal const val TARGET_SDK = 37
internal const val MIN_SDK = 26
internal val JVM_TARGET = JvmTarget.JVM_17
private val JAVA_VERSION = JavaVersion.VERSION_17

/**
 * What every Android module shares: SDK levels, Java/Kotlin 17 bytecode, Kotlin and Lint
 * warnings as errors.
 */
internal fun Project.configureAndroid(android: CommonExtension) {
    android.apply {
        compileSdk = COMPILE_SDK
        defaultConfig.minSdk = MIN_SDK

        compileOptions.apply {
            sourceCompatibility = JAVA_VERSION
            targetCompatibility = JAVA_VERSION
        }

        lint.apply {
            warningsAsErrors = true
            abortOnError = true
            checkReleaseBuilds = true
        }
    }

    extensions.configure<KotlinAndroidProjectExtension> {
        compilerOptions {
            jvmTarget.set(JVM_TARGET)
            allWarningsAsErrors.set(true)
        }
    }
}
