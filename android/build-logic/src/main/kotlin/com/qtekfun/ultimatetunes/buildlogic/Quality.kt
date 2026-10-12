// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.buildlogic

import app.cash.licensee.LicenseeExtension
import io.gitlab.arturbosch.detekt.Detekt
import io.gitlab.arturbosch.detekt.extensions.DetektExtension
import kotlinx.kover.gradle.plugin.dsl.KoverProjectExtension
import org.gradle.api.GradleException
import org.gradle.api.Project
import org.gradle.api.artifacts.VersionCatalog
import org.gradle.api.artifacts.VersionCatalogsExtension
import org.gradle.api.artifacts.component.ModuleComponentIdentifier
import org.gradle.api.artifacts.result.ResolvedComponentResult
import org.gradle.api.artifacts.result.ResolvedDependencyResult
import org.gradle.api.tasks.testing.Test
import org.gradle.kotlin.dsl.configure
import org.gradle.kotlin.dsl.getByType
import org.gradle.kotlin.dsl.withType
import org.jlleitschuh.gradle.ktlint.KtlintExtension

/** Google Play Services, Firebase, Crashlytics and Sentry: banned outright (CLAUDE.md). */
private val FORBIDDEN_GROUP_PREFIXES = listOf(
    "com.google.android.gms",
    "com.google.firebase",
    "com.crashlytics",
    "io.fabric",
    "io.sentry"
)

/** What ships: every Android module has these. */
private val SHIPPED_CLASSPATHS = listOf("debugRuntimeClasspath", "releaseRuntimeClasspath")

/** What runs in tests, on a JVM or on a device; checked where the module has them. */
private val TEST_CLASSPATHS = listOf(
    "debugUnitTestRuntimeClasspath",
    "releaseUnitTestRuntimeClasspath",
    "debugAndroidTestRuntimeClasspath"
)

/** Kover variant on which :app verifies the 100 % packages. */
const val CRITICAL_COVERAGE_VARIANT = "critical"

internal val Project.libs: VersionCatalog
    get() = extensions.getByType<VersionCatalogsExtension>().named("libs")

/**
 * The quality gates every Android module shares: detekt, ktlint, licensee, Kover, the
 * forbidden-dependency check (all wired into `check`) and JUnit 5 for unit tests.
 */
internal fun Project.configureQuality() {
    with(pluginManager) {
        apply("io.gitlab.arturbosch.detekt")
        apply("org.jlleitschuh.gradle.ktlint")
        apply("org.jetbrains.kotlinx.kover")
        apply("app.cash.licensee")
    }

    extensions.configure<DetektExtension> {
        buildUponDefaultConfig = true
        allRules = false
        config.setFrom(isolated.rootProject.projectDirectory.file("config/detekt/detekt.yml"))
        source.setFrom(
            "src/main/java",
            "src/main/kotlin",
            "src/debug/java",
            "src/test/java",
            "src/test/kotlin",
            "src/androidTest/java",
            "src/androidTest/kotlin"
        )
    }
    tasks.withType<Detekt>().configureEach {
        // Match the project bytecode level; detekt defaults to the JDK running Gradle.
        jvmTarget = JVM_TARGET.target
    }

    extensions.configure<KtlintExtension> {
        version.set(libs.findVersion("ktlint").get().requiredVersion)
    }

    // Only GPL-3.0-compatible free licenses may ship in the APK. Anything else, including
    // dependencies without a declared license, fails the build. Add other GPL-3.0-compatible
    // SPDX ids (MIT, BSD-2-Clause, BSD-3-Clause, ISC...) only when a dependency needs them.
    extensions.configure<LicenseeExtension> {
        allow("Apache-2.0")
    }

    // The "critical" coverage variant (debug build) of every module: :app merges them and verifies
    // the 100 % packages of CLAUDE.md on it (koverVerifyCritical, see app/build.gradle.kts).
    extensions.configure<KoverProjectExtension> {
        currentProject {
            createVariant(CRITICAL_COVERAGE_VARIANT) {
                add("debug")
            }
        }
    }

    tasks.withType<Test>().configureEach {
        useJUnitPlatform()
    }
    with(dependencies) {
        add("testImplementation", platform(libs.findLibrary("junit-bom").get()))
        add("testImplementation", libs.findLibrary("junit-jupiter").get())
        add("testRuntimeOnly", libs.findLibrary("junit-platform-launcher").get())
    }

    registerForbiddenDependencyCheck()
}

private fun Project.registerForbiddenDependencyCheck() {
    val check = tasks.register("checkForbiddenDependencies") {
        group = "verification"
        description = "Fails if a runtime classpath contains Google Play Services, Firebase, " +
            "Crashlytics or Sentry."
        val shipped = SHIPPED_CLASSPATHS.map { name -> configurations.named(name).get() }
        val tests = TEST_CLASSPATHS.mapNotNull { name -> configurations.findByName(name) }
        val roots = (shipped + tests).map { it.incoming.resolutionResult.rootComponent }
        doLast {
            val offenders = modulesOf(roots.map { it.get() })
                .filter { module -> FORBIDDEN_GROUP_PREFIXES.any { module.startsWith(it) } }
                .sorted()
            if (offenders.isNotEmpty()) {
                throw GradleException(
                    "Forbidden non-free dependencies found: ${offenders.joinToString()}"
                )
            }
        }
    }
    tasks.named("check") { dependsOn(check) }
}

/** Every external module (group:name) reachable from [roots]. */
private fun modulesOf(roots: List<ResolvedComponentResult>): Set<String> {
    val modules = mutableSetOf<String>()
    val seen = mutableSetOf<ResolvedComponentResult>()
    val pending = ArrayDeque(roots)
    while (pending.isNotEmpty()) {
        val component = pending.removeFirst()
        if (seen.add(component)) {
            (component.id as? ModuleComponentIdentifier)?.let {
                modules.add(it.moduleIdentifier.toString())
            }
            component.dependencies
                .filterIsInstance<ResolvedDependencyResult>()
                .forEach { pending.add(it.selected) }
        }
    }
    return modules
}
