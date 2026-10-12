// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// Playback with Media3: the session service, the client cache, the prefetch planner, ReplayGain
// and offline downloads (PLAN T17).

plugins {
    id("ut.android.library")
    alias(libs.plugins.kotlin.serialization)
    alias(libs.plugins.ksp)
    alias(libs.plugins.hilt)
}

android {
    namespace = "com.qtekfun.ultimatetunes.core.player"
}

dependencies {
    // One Media3 version for all artifacts; datasource-okhttp streams through the OkHttp client of
    // :core:api, which adds the credentials (SPEC §11, T02).
    api(libs.media3.exoplayer)
    // api: the app's playback package binds a MediaController to the session service.
    api(libs.media3.session)
    implementation(libs.media3.datasource.okhttp)
    // Brings the client and pins OkHttp to the app's version (media3-datasource-okhttp asks for 4.x).
    api(project(":core:api"))
    implementation(libs.kotlinx.coroutines.android)
    // The offline selection, and its sync in the background (RF-12).
    implementation(libs.androidx.datastore.preferences)
    implementation(libs.androidx.work.runtime)

    implementation(libs.hilt.android)
    ksp(libs.hilt.compiler)

    testImplementation(libs.kotlinx.coroutines.test)
    testImplementation(libs.mockk)
}
