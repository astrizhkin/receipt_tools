import java.io.FileInputStream
import java.util.Properties

plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

// Release signing: key.properties (gitignored) gives the keystore path + alias;
// the passwords live OUTSIDE the repo in /secrets/storepass.txt, which
// demo/build_apk.sh mounts read-only into the builder container. Without those
// files the release build falls back to debug signing (dev convenience).
// key.properties lives in android/ (root project), not the app module dir
val keystorePropsFile = rootProject.file("key.properties")
val storePassFile = file("/secrets/storepass.txt")
val useReleaseSigning = keystorePropsFile.exists() && storePassFile.exists()

android {
    namespace = "com.biarum.receipt_tools"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        // required by ota_update 7.x (java.time desugaring)
        isCoreLibraryDesugaringEnabled = true
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        applicationId = "com.biarum.receipt_tools"
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        // Uses the version code from pubspec.yaml. NEVER build --split-per-abi:
        // it rewrites versionCode (1000*ABI) and breaks the in-app update
        // version comparison.
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    signingConfigs {
        if (useReleaseSigning) {
            create("release") {
                val props = Properties().apply { load(FileInputStream(keystorePropsFile)) }
                storeFile = file(props.getProperty("storeFile"))
                keyAlias = props.getProperty("keyAlias")
                val pass = storePassFile.readText().trim()
                storePassword = pass
                keyPassword = pass
            }
        }
    }

    buildTypes {
        release {
            signingConfig = if (useReleaseSigning) {
                signingConfigs.getByName("release")
            } else {
                signingConfigs.getByName("debug")
            }
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

dependencies {
    coreLibraryDesugaring("com.android.tools:desugar_jdk_libs:2.1.5")
    // FileProvider for the APK install channel in MainActivity
    implementation("androidx.core:core:1.15.0")
}

flutter {
    source = "../.."
}
