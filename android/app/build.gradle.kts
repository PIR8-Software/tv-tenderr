plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.movieswipe"
    compileSdk = 34

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
    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        viewBinding = true
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.12.0")
    implementation("androidx.appcompat:appcompat:1.6.1")
    implementation("com.google.android.material:material:1.11.0")
    implementation("androidx.constraintlayout:constraintlayout:2.1.4")
    implementation("androidx.recyclerview:recyclerview:1.3.2")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.google.code.gson:gson:2.10.1")
    implementation("com.github.bumptech.glide:glide:4.16.0")
    implementation("androidx.cardview:cardview:1.0.0")
    implementation("androidx.security:security-crypto:1.0.0")

    testImplementation("junit:junit:4.13.2")
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
}
