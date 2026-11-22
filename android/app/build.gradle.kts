import org.jetbrains.kotlin.gradle.dsl.JvmTarget
import java.util.Properties

// Optional release key: create android/keystore.properties (never commit it) with
// storeFile, storePassword, keyAlias, keyPassword. Without it, release builds use the public test key.
val releaseKeyProps = Properties().apply {
    rootProject.file("keystore.properties").takeIf { it.exists() }?.inputStream()?.use { load(it) }
}

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.ksp)
}

android {
    namespace = "com.cashbook.app"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.cashbook.app"
        minSdk = 26
        targetSdk = 36
        versionCode = 2
        versionName = "1.1.0"
        vectorDrawables { useSupportLibrary = true }
    }

    signingConfigs {
        // Test-only signing key committed to the repository so anyone can build an
        // installable APK. Replace with your own upload key before publishing.
        create("test") {
            storeFile = file("cashbook-test.keystore")
            storePassword = "cashbook-test"
            keyAlias = "cashbook"
            keyPassword = "cashbook-test"
        }
        if (releaseKeyProps.isNotEmpty()) create("upload") {
            storeFile = rootProject.file(releaseKeyProps.getProperty("storeFile"))
            storePassword = releaseKeyProps.getProperty("storePassword")
            keyAlias = releaseKeyProps.getProperty("keyAlias")
            keyPassword = releaseKeyProps.getProperty("keyPassword")
        }
    }

    buildTypes {
        debug {
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
        }
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = signingConfigs.findByName("upload") ?: signingConfigs.getByName("test")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
    androidResources {
        @Suppress("UnstableApiUsage")
        generateLocaleConfig = true
        localeFilters += listOf("en", "hi")
    }
    // Room schemas for MigrationTest (Robolectric reads the merged debug assets; release APKs never include them)
    sourceSets["debug"].assets.srcDir("$projectDir/schemas")
    testOptions {
        unitTests {
            isIncludeAndroidResources = true
            all {
                it.systemProperty("robolectric.graphicsMode", "NATIVE")
                it.maxHeapSize = "3g"
            }
        }
    }
    packaging {
        resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
    }
}

kotlin {
    compilerOptions { jvmTarget.set(JvmTarget.JVM_17) }
}

ksp {
    arg("room.schemaLocation", "$projectDir/schemas")
}

dependencies {
    implementation(project(":core"))

    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.appcompat)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.lifecycle.process)
    implementation(libs.androidx.navigation.compose)

    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.material3)
    implementation(libs.compose.material.icons.extended)
    implementation(libs.compose.ui.tooling.preview)
    debugImplementation(libs.compose.ui.tooling)

    implementation(libs.room.runtime)
    implementation(libs.room.ktx)
    ksp(libs.room.compiler)
    implementation(libs.sqlcipher)
    implementation(libs.sqlite)

    implementation(libs.datastore.preferences)
    implementation(libs.work.runtime.ktx)
    implementation(libs.biometric)
    implementation(libs.documentfile)

    testImplementation(libs.junit)
    testImplementation(libs.robolectric)
    testImplementation(libs.androidx.test.core)
    testImplementation(libs.androidx.test.junit)
    testImplementation(platform(libs.compose.bom))
    testImplementation(libs.compose.ui.test.junit4)
    testImplementation(libs.kotlinx.coroutines.test)
    testImplementation(libs.room.testing)
    debugImplementation(libs.compose.ui.test.manifest)
}

// Robolectric's Android runtime jar is resolved by Gradle (cached, retried) instead of being
// downloaded by Robolectric at test time, so unit tests also run offline after the first build.
val robolectricRuntime: Configuration by configurations.creating { isTransitive = false }
dependencies { robolectricRuntime("org.robolectric:android-all-instrumented:15-robolectric-13954326-i7") }
val robolectricDepsDir = layout.buildDirectory.dir("robolectric-deps")
val fetchRobolectricRuntime by tasks.registering(Copy::class) {
    onlyIf { robolectricDepsDir.get().asFile.listFiles()?.any { it.name.startsWith("android-all-instrumented-15") } != true }
    from(robolectricRuntime)
    into(robolectricDepsDir)
}
tasks.withType<Test>().configureEach {
    dependsOn(fetchRobolectricRuntime)
    systemProperty("robolectric.offline", "true")
    systemProperty("robolectric.dependency.dir", robolectricDepsDir.get().asFile.absolutePath)
}
