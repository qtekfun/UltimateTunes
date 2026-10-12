// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// Playback with Media3 and the client cache (filled in by PLAN T17).

plugins {
    id("ut.android.library")
}

android {
    namespace = "com.qtekfun.ultimatetunes.core.player"
}

dependencies {
    // One Media3 version for all artifacts; datasource-okhttp streams through the OkHttp client of
    // :core:api, which adds the credentials (SPEC §11, T02).
    implementation(libs.media3.exoplayer)
    // api: the app's playback package (T17) binds a MediaController to the session service.
    api(libs.media3.session)
    implementation(libs.media3.datasource.okhttp)
    // Brings the client and pins OkHttp to the app's version (media3-datasource-okhttp asks for 4.x).
    implementation(project(":core:api"))
}
