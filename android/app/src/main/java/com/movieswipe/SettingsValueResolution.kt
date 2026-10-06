package com.movieswipe

fun preferBackendSetting(localValue: String, backendValue: String, defaultValue: String): String =
    if (localValue.isBlank() || localValue == defaultValue) backendValue else localValue

fun settingsSaveMessage(responseSuccessful: Boolean): String =
    if (responseSuccessful) "Settings saved" else "Saved locally (backend rejected settings)"

fun configuredSetting(value: String, defaultValue: String): String? =
    value.trim().takeIf { it.isNotEmpty() && it != defaultValue }

val SECRET_PREF_KEYS = listOf("radarr_key", "sonarr_key", "plex_token", "tmdb_key", "api_token")

fun migratedSecrets(plain: Map<String, String?>, encrypted: Map<String, String?>): Map<String, String> {
    val result = linkedMapOf<String, String>()
    for (key in SECRET_PREF_KEYS) {
        val current = encrypted[key]?.trim().orEmpty()
        val legacy = plain[key]?.trim().orEmpty()
        val chosen = current.ifEmpty { legacy }
        if (chosen.isNotEmpty()) result[key] = chosen
    }
    return result
}

fun plaintextSecretsToRemove(plain: Map<String, String?>, encryptedAfter: Map<String, String>): Set<String> =
    SECRET_PREF_KEYS.filter { plain.containsKey(it) && !encryptedAfter[it].isNullOrBlank() }.toSet()

fun settingsConfigPayload(
    values: Map<String, String>,
    defaults: Map<String, String>,
    radarrQualityId: Int?,
    sonarrQualityId: Int?,
    radarrRoot: String?,
    sonarrRoot: String?,
): Map<String, String> {
    val payload = linkedMapOf<String, String>()
    for ((key, value) in values) {
        configuredSetting(value, defaults[key] ?: "")?.let { payload[key] = it }
    }
    if (radarrQualityId != null && radarrQualityId > 0) payload["radarrQualityId"] = radarrQualityId.toString()
    if (sonarrQualityId != null && sonarrQualityId > 0) payload["sonarrQualityId"] = sonarrQualityId.toString()
    radarrRoot?.trim()?.takeIf { it.isNotEmpty() }?.let { payload["radarrRootFolder"] = it }
    sonarrRoot?.trim()?.takeIf { it.isNotEmpty() }?.let { payload["sonarrRootFolder"] = it }
    // Client login is not server token rotation. Bootstrap is a local web operation.
    return payload
}
