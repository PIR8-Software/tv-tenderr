plugins {
    id("com.android.application")
}

android {
    namespace = "com.movieswipe"
    compileSdk = 37

    defaultConfig {
        applicationId = "com.movieswipe"
        minSdk = 26
        targetSdk = 34
        versionCode = 10304
        versionName = "1.3.4"
    }

    signingConfigs {
        create("release") {
            storeFile = file("tv-tenderr-release.jks")
            storePassword = providers.gradleProperty("TV_TENDERR_KEYSTORE_PASSWORD").orNull
                ?: System.getenv("KEYSTORE_PASSWORD")
                ?: throw GradleException("TV Tenderr keystore password is not configured")
            keyAlias = "tv-tenderr"
            keyPassword = providers.gradleProperty("TV_TENDERR_KEY_PASSWORD").orNull
                ?: System.getenv("KEY_PASSWORD")
                ?: throw GradleException("TV Tenderr key password is not configured")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("release")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        viewBinding = true
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.12.0")
    implementation("androidx.appcompat:appcompat:1.6.1")
    implementation("com.google.android.material:material:1.11.0")
    implementation("androidx.constraintlayout:constraintlayout:2.2.2")
    implementation("androidx.recyclerview:recyclerview:1.3.2")
    implementation("com.squareup.okhttp3:okhttp:5.5.0")
    implementation("com.google.code.gson:gson:2.14.0")
    implementation("com.github.bumptech.glide:glide:4.16.0")
    implementation("androidx.cardview:cardview:1.0.0")
    implementation("androidx.security:security-crypto:1.0.0")

    testImplementation("junit:junit:4.13.2")
    testImplementation("com.squareup.okhttp3:mockwebserver:5.5.0")
}
