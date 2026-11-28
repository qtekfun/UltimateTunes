// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The local catalog of the library: its database, sync, search and pending changes (PLAN T32-T35).

plugins {
    id("ut.android.library")
    alias(libs.plugins.kotlin.serialization)
    alias(libs.plugins.ksp)
    alias(libs.plugins.room)
}

android {
    namespace = "com.qtekfun.ultimatetunes.core.library"
}

// The schema of each database version, committed so later versions can write their migrations.
room3 {
    schemaDirectory("$projectDir/schemas")
}

dependencies {
    // The catalog is filled through `TunesApi`.
    api(project(":core:api"))
    implementation(libs.room.runtime)
    implementation(libs.kotlinx.serialization.json)
    ksp(libs.room.compiler)

    testImplementation(testFixtures(project(":core:api")))
    // A real SQLite for the JVM tests (on a device the driver of room3-runtime is used).
    testImplementation(libs.sqlite.bundled.jvm)
}
