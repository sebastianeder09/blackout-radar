import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Laufende Nummer des Baus, bei GitHub die Nummer des Laufs. Höher heißt neuer.
val buildNumber = (findProperty("buildNumber") as String?)?.toIntOrNull() ?: 1

// Kennwort zum Schlüssel, mit dem der Bau für Google Play unterschrieben wird (bei GitHub das Secret
// PLAY_UPLOAD_PASSWORD). Ohne Kennwort entsteht das Paket für Google Play ohne Unterschrift.
val uploadPassword: String? = System.getenv("PLAY_UPLOAD_PASSWORD")?.takeIf { it.isNotBlank() }

// Impressum und Datenschutzerklärung stehen einmal im Repository (docs/). Von dort kommen sie in die App.
val legalDir = layout.buildDirectory.dir("rechtstexte")
val legalTexts = tasks.register<Copy>("rechtstexte") {
    from(rootProject.file("../docs")) {
        include("impressum.md", "datenschutz.md")
    }
    into(legalDir.map { it.dir("rechtstexte") })
}

android {
    namespace = "io.github.sebastianeder09.blackoutradar"
    compileSdk = 36

    defaultConfig {
        applicationId = "io.github.sebastianeder09.blackoutradar"
        minSdk = 26
        targetSdk = 36
        versionCode = buildNumber
        versionName = "1.$buildNumber"
        buildConfigField("String", "REPO", "\"sebastianeder09/blackout-radar\"")
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
        // Für Google Play. Die Datei liegt im Repository, ihr Kennwort nicht: Ohne das Kennwort ist sie wertlos.
        if (uploadPassword != null) {
            create("upload") {
                storeFile = rootProject.file("keystore/play-upload.p12")
                storeType = "pkcs12"
                storePassword = uploadPassword
                keyAlias = "upload"
                keyPassword = uploadPassword
            }
        }
    }

    // Zwei Wege zum Handy, ein Programm. Wer unterschreibt, entscheidet der Weg (signingConfig je Variante).
    flavorDimensions += "weg"
    productFlavors {
        // Die Installationsdatei aus diesem Repository. Sie hält sich selbst aktuell und gibt sich samt Thema
        // als Datei weiter (AppFile.kt): Das setzt voraus, dass die Datei am Handy dieselbe ist, die hier
        // signiert wurde.
        create("github") {
            dimension = "weg"
            buildConfigField("boolean", "PLAY", "false")
            buildConfigField("boolean", "APP_FILE", "true")
            signingConfig = signingConfigs.getByName("release")
        }
        // Das Paket für Google Play, mit eigenem Namen: Beide lassen sich nebeneinander installieren. Google
        // signiert und verteilt die App selbst, auch neue Fassungen. Die Weitergabe als Datei entfällt deshalb.
        create("play") {
            dimension = "weg"
            applicationId = "at.ase_it.blackoutradar"
            buildConfigField("boolean", "PLAY", "true")
            buildConfigField("boolean", "APP_FILE", "false")
            signingConfig = signingConfigs.findByName("upload")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            // Kein signingConfig an dieser Stelle: Es ginge dem der Variante vor.
        }
        debug {
            // Der Testbau lässt sich neben der echten App installieren.
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-test"
        }
    }

    sourceSets {
        getByName("main") {
            assets.srcDir(legalDir.get().asFile)
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

// Die Rechtstexte müssen liegen, bevor irgendein Schritt die Dateien der App einsammelt.
tasks.named("preBuild") {
    dependsOn(legalTexts)
}

dependencies {
    testImplementation("junit:junit:4.13.2")
    // org.json gehört zu Android, fehlt aber in den Tests auf dem Rechner.
    testImplementation("org.json:json:20250517")
}
