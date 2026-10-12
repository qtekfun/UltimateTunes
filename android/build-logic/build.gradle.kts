// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    `kotlin-dsl`
    alias(libs.plugins.detekt)
    alias(libs.plugins.ktlint)
}

group = "com.qtekfun.ultimatetunes.buildlogic"

java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}

kotlin {
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_17)
        allWarningsAsErrors.set(true)
    }
}

detekt {
    buildUponDefaultConfig = true
    allRules = false
    config.setFrom(file("../config/detekt/detekt.yml"))
}

tasks.withType<io.gitlab.arturbosch.detekt.Detekt>().configureEach {
    jvmTarget = "17"
}

ktlint {
    version.set(libs.versions.ktlint)
}

dependencies {
    // compileOnly: the main build puts these plugins on its classpath (root build.gradle.kts).
    compileOnly(libs.android.gradle.plugin)
    compileOnly(libs.kotlin.gradle.plugin)
    compileOnly(libs.detekt.gradle.plugin)
    compileOnly(libs.ktlint.gradle.plugin)
    compileOnly(libs.kover.gradle.plugin)
    compileOnly(libs.licensee.gradle.plugin)

    testImplementation(platform(libs.junit.bom))
    testImplementation(libs.junit.jupiter)
    testRuntimeOnly(libs.junit.platform.launcher)
}

tasks.test {
    useJUnitPlatform()
}

val conventions = "com.qtekfun.ultimatetunes.buildlogic"

gradlePlugin {
    plugins {
        register("androidApplication") {
            id = "ut.android.application"
            implementationClass = "$conventions.AndroidApplicationConventionPlugin"
        }
        register("androidLibrary") {
            id = "ut.android.library"
            implementationClass = "$conventions.AndroidLibraryConventionPlugin"
        }
    }
}
