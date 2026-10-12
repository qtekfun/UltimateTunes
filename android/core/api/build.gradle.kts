// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// HTTP client (`TunesApi`), models and the contract-backed fake server of the UltimateTunes API.

plugins {
    id("ut.android.library")
    alias(libs.plugins.kotlin.serialization)
    alias(libs.plugins.ksp)
    alias(libs.plugins.hilt)
}

android {
    namespace = "com.qtekfun.ultimatetunes.core.api"

    // The fake server (`FakeTunesServer`) lives in the test fixtures, so `:app` tests can use it
    // with `testImplementation(testFixtures(project(":core:api")))` and it never reaches an APK.
    testFixtures {
        enable = true
    }
}

/**
 * The OpenAPI contracts whose examples the fake server serves. The fixture copies in
 * `src/testFixtures/resources/contract-examples` are checked against them by
 * `ContractExamplesTest`; run the unit tests with `-PupdateContractFixtures` to rewrite the copies
 * after a contract change.
 */
val contractsDir: Directory = isolated.rootProject.projectDirectory.dir("../contracts/openapi")
val fixturesDir: Directory =
    layout.projectDirectory.dir("src/testFixtures/resources/contract-examples")
val updateContractFixtures: Boolean = providers.gradleProperty("updateContractFixtures").isPresent

tasks.withType<Test>().configureEach {
    inputs.dir(contractsDir)
        .withPathSensitivity(PathSensitivity.RELATIVE)
        .withPropertyName("contracts")
    systemProperty("ut.contractsDir", contractsDir.asFile.absolutePath)
    systemProperty("ut.fixturesDir", fixturesDir.asFile.absolutePath)
    systemProperty("ut.updateContractFixtures", updateContractFixtures.toString())
    if (updateContractFixtures) {
        outputs.upToDateWhen { false }
    }
}

dependencies {
    api(libs.okhttp)
    api(libs.kotlinx.serialization.json)
    implementation(libs.kotlinx.coroutines.android)

    implementation(libs.hilt.android)
    ksp(libs.hilt.compiler)

    testFixturesApi(libs.okhttp)
    testFixturesApi(libs.okhttp.mockwebserver)
    testFixturesImplementation(libs.kotlinx.serialization.json)

    testImplementation(libs.okhttp.mockwebserver)
    testImplementation(libs.kotlinx.coroutines.test)
    testImplementation(libs.mockk)
}
