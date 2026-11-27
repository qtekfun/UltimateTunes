// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The local catalog of the library: its database, sync, search and pending changes (PLAN T32-T35).

plugins {
    id("ut.android.library")
}

android {
    namespace = "com.qtekfun.ultimatetunes.core.library"
}

dependencies {
    // The catalog is filled through `TunesApi`.
    api(project(":core:api"))
}
