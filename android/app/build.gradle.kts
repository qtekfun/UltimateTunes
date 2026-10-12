// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

import com.qtekfun.ultimatetunes.buildlogic.versionCodeOf
import kotlinx.kover.gradle.plugin.dsl.CoverageUnit
import kotlinx.kover.gradle.plugin.dsl.KoverReportFilter

plugins {
    id("ut.android.application")
    alias(libs.plugins.ksp)
    alias(libs.plugins.hilt)
}

/**
 * One version for the whole repository: the root `VERSION` file (SemVer, optionally `-rc.N`),
 * changed only in a release PR (RELEASING.md). The version code is derived from it
 * (`versionCodeOf` in build-logic, same formula as tools/version-code.sh).
 */
val appVersion: String = providers
    .fileContents(isolated.rootProject.projectDirectory.file("../VERSION"))
    .asText
    .get()
    .trim()

/** Release signing from the environment (CI secrets); without it the release APK is unsigned. */
val releaseKeystore: String? = providers.environmentVariable("UT_KEYSTORE_FILE").orNull

android {
    namespace = "com.qtekfun.ultimatetunes"

    defaultConfig {
        applicationId = "com.qtekfun.ultimatetunes"
        versionCode = versionCodeOf(appVersion)
        versionName = appVersion
        testInstrumentationRunner = "com.qtekfun.ultimatetunes.HiltTestRunner"
    }

    signingConfigs {
        if (releaseKeystore != null) {
            create("release") {
                storeFile = file(releaseKeystore)
                storePassword = providers.environmentVariable("UT_KEYSTORE_PASSWORD").orNull
                keyAlias = providers.environmentVariable("UT_KEY_ALIAS").orNull
                keyPassword = providers.environmentVariable("UT_KEY_PASSWORD").orNull
            }
        }
    }

    buildTypes {
        release {
            signingConfig = signingConfigs.findByName("release")
            // The git commit is not part of the APK: a build from a source tarball must match.
            vcsInfo.include = false
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    testOptions {
        // UI tests wait on idling, not on timers: no animation may be running.
        animationsDisabled = true
    }
}

// Coverage policy (CLAUDE.md): >= 85 % (lines) over the :core modules and the view models.
// Generated code and pure Compose UI are excluded.
val coveredPackages = listOf("com.qtekfun.ultimatetunes.core")
val coveredClasses = listOf("*ViewModel")

/**
 * The 100 % areas of CLAUDE.md (client cache policy, queue prefetch planner,
 * streaming-while-downloading state machine...), as packages. PLAN T01 fills it in; each
 * package listed here must then reach 100 % of lines and branches.
 */
val criticalPackages = emptyList<String>()

/**
 * Generated code and pure Compose UI, excluded from coverage. Applied to each report variant:
 * variant filters replace the global ones instead of adding to them.
 */
fun KoverReportFilter.generatedAndUiCode() {
    packages("dagger.hilt.internal", "hilt_aggregated_deps")
    classes(
        "*.R",
        "*.R$*",
        "*.BuildConfig",
        "*Hilt_*",
        "*_HiltModules*",
        "*_Factory",
        "*_Factory$*",
        "*_MembersInjector",
        // Room
        "*_Impl",
        "*_Impl$*",
        // Kotlin compatibility bridges for interface default methods
        "*\$DefaultImpls",
        "*ComposableSingletons*"
    )
    annotatedBy(
        "androidx.compose.runtime.Composable",
        "androidx.compose.ui.tooling.preview.Preview",
        "dagger.Module",
        "dagger.hilt.android.HiltAndroidApp",
        "*Generated*"
    )
}

kover {
    if (criticalPackages.isNotEmpty()) {
        currentProject {
            createVariant("critical") {
                add("debug")
            }
        }
    }

    reports {
        total {
            filters {
                excludes { generatedAndUiCode() }
                includes {
                    packages(coveredPackages)
                    classes(coveredClasses)
                }
            }
            verify {
                rule("core modules and view models") {
                    minBound(85, CoverageUnit.LINE)
                }
            }
        }

        if (criticalPackages.isNotEmpty()) {
            variant("critical") {
                filters {
                    excludes { generatedAndUiCode() }
                    includes { packages(criticalPackages) }
                }
                verify {
                    rule("100 % areas") {
                        minBound(100, CoverageUnit.LINE)
                        minBound(100, CoverageUnit.BRANCH)
                    }
                }
            }
        }
    }
}

if (criticalPackages.isNotEmpty()) {
    tasks.named("koverVerify") {
        dependsOn("koverVerifyCritical")
    }
}

tasks.named("check") {
    dependsOn("koverVerify")
}

dependencies {
    implementation(project(":core:api"))
    implementation(project(":core:player"))
    // Coverage of the :core modules is measured and verified here, together with the app's.
    kover(project(":core:api"))
    kover(project(":core:player"))

    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.lifecycle.runtime.compose)

    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.compose.material3)
    debugImplementation(libs.androidx.compose.ui.tooling)

    implementation(libs.hilt.android)
    ksp(libs.hilt.compiler)

    // UI tests, run on a device with installDebug installDebugAndroidTest + adb instrument
    // (never connectedDebugAndroidTest on the author's phone).
    androidTestImplementation(platform(libs.androidx.compose.bom))
    androidTestImplementation(libs.androidx.compose.ui.test.junit4)
    androidTestImplementation(libs.androidx.test.runner)
    androidTestImplementation(libs.androidx.test.ext.junit)
    // Compose's test rule brings Espresso 3.5, which calls an API Android 17 removed.
    androidTestImplementation(libs.androidx.test.espresso.core)
    androidTestImplementation(libs.hilt.android.testing)
    kspAndroidTest(libs.hilt.compiler)
    debugImplementation(libs.androidx.compose.ui.test.manifest)

    testImplementation(libs.kotlinx.coroutines.test)
    testImplementation(libs.turbine)
    testImplementation(libs.mockk)
}
