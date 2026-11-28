import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Laufende Nummer des Baus, bei GitHub die Nummer des Laufs. Höher heißt neuer.
val buildNumber = (findProperty("buildNumber") as String?)?.toIntOrNull() ?: 1

android {
    namespace = "io.github.sebastianeder09.blackoutradar"
    compileSdk = 35

    defaultConfig {
        applicationId = "io.github.sebastianeder09.blackoutradar"
        minSdk = 26
        targetSdk = 35
        versionCode = buildNumber
        versionName = "1.$buildNumber"
        buildConfigField("String", "REPO", "\"sebastianeder09/blackout-radar\"")
        // Die App samt Thema als Datei weitergeben (AppFile.kt). Das setzt voraus, dass die Installationsdatei
        // am Handy dieselbe ist, die hier signiert wurde. Ein Bau für einen Store, der selbst signiert, stellt das ab.
        buildConfigField("boolean", "APP_FILE", "true")
    }

    signingConfigs {
        // Absichtlich öffentlich, siehe android/README.md: Die App kommt nur aus diesem Repository.
        create("release") {
            storeFile = rootProject.file("keystore/blackout-radar.p12")
            storeType = "pkcs12"
            storePassword = "blackout-radar"
            keyAlias = "blackout-radar"
            keyPassword = "blackout-radar"
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = signingConfigs.getByName("release")
        }
        debug {
            // Der Testbau lässt sich neben der echten App installieren.
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-test"
        }
    }

    buildFeatures {
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    lint {
        checkReleaseBuilds = false
    }

    testOptions {
        unitTests.isReturnDefaultValues = true
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_17)
    }
}

dependencies {
    testImplementation("junit:junit:4.13.2")
    // org.json gehört zu Android, fehlt aber in den Tests auf dem Rechner.
    testImplementation("org.json:json:20250517")
}
