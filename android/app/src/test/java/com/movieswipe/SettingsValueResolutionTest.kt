package com.movieswipe

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class SettingsValueResolutionTest {
    @Test
    fun backendValuesReplaceFirstRunDefaultsButNotRealLocalEdits() {
        assertEquals(
            "http://radarr.test",
            preferBackendSetting("http://localhost:7878", "http://radarr.test", "http://localhost:7878"),
        )
        assertEquals(
            "real-key",
            preferBackendSetting("YOUR_RADARR_API_KEY", "real-key", "YOUR_RADARR_API_KEY"),
        )
        assertEquals(
            "http://custom-radarr",
            preferBackendSetting("http://custom-radarr", "http://radarr.test", "http://localhost:7878"),
        )
    }

    @Test
    fun settingsSaveMessageDoesNotReportRejectedRequestsAsSaved() {
        assertEquals("Settings saved", settingsSaveMessage(true))
        assertEquals("Saved locally (backend rejected settings)", settingsSaveMessage(false))
    }

    @Test
    fun placeholderSettingsAreNotPushedToANewBackend() {
        assertEquals(null, configuredSetting("YOUR_RADARR_API_KEY", "YOUR_RADARR_API_KEY"))
        assertEquals(null, configuredSetting("http://localhost:7878", "http://localhost:7878"))
        assertEquals("real-key", configuredSetting("real-key", "YOUR_RADARR_API_KEY"))
    }

    @Test
    fun secretMigrationKeepsExistingEncryptedValuesAndClearsPlaintextCopies() {
        val migrated = migratedSecrets(
            plain = mapOf("radarr_key" to "legacy-key", "plex_token" to "legacy-plex"),
            encrypted = mapOf("radarr_key" to "encrypted-key"),
        )
        assertEquals("encrypted-key", migrated["radarr_key"])
        assertEquals("legacy-plex", migrated["plex_token"])
        assertEquals(
            setOf("radarr_key", "plex_token"),
            plaintextSecretsToRemove(
                mapOf("radarr_key" to "legacy-key", "plex_token" to "legacy-plex", "server_url" to "http://x"),
                migrated,
            ),
        )
    }

    @Test
    fun settingsPayloadIncludesQualityRootWithoutRotatingTokenOrPushingPlaceholders() {
        val payload = settingsConfigPayload(
            values = mapOf(
                "radarrUrl" to "http://radarr.test",
                "radarrKey" to "YOUR_RADARR_API_KEY",
                "sonarrUrl" to "http://localhost:8989",
            ),
            defaults = mapOf(
                "radarrUrl" to "http://localhost:7878",
                "radarrKey" to "YOUR_RADARR_API_KEY",
                "sonarrUrl" to "http://localhost:8989",
            ),
            radarrQualityId = 6,
            sonarrQualityId = null,
            radarrRoot = "H:\\Movies",
            sonarrRoot = "  ",
        )
        assertEquals("http://radarr.test", payload["radarrUrl"])
        assertEquals("6", payload["radarrQualityId"])
        assertEquals("H:\\Movies", payload["radarrRootFolder"])
        assertFalse(payload.containsKey("apiToken"))
        assertFalse(payload.containsKey("radarrKey"))
        assertFalse(payload.containsKey("sonarrUrl"))
        assertFalse(payload.containsKey("sonarrRootFolder"))
    }
}
