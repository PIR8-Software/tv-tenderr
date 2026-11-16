package com.movieswipe

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * Regression tests for F5: validate the HTTP(S) backend URL before any
 * persistence, retain the previous valid configuration on invalid input, and
 * resolve invalid stored configuration to a safe fallback without crashing.
 */
class BackendUrlTest {

    @Test
    fun validHttpAndHttpsUrlsAreAccepted() {
        assertEquals("http://localhost:8899", BackendUrl.normalize("http://localhost:8899"))
        assertEquals(
            "https://media.example:8443",
            BackendUrl.normalize("https://media.example:8443"),
        )
        assertEquals(
            "http://192.168.1.5:8899",
            BackendUrl.normalize("  http://192.168.1.5:8899  "),
        )
    }

    @Test
    fun trailingSlashIsNormalizedAway() {
        assertEquals(
            "http://localhost:8899",
            BackendUrl.normalize("http://localhost:8899/"),
        )
    }

    @Test
    fun blankAndWhitespaceAreRejected() {
        assertNull(BackendUrl.normalize(""))
        assertNull(BackendUrl.normalize("   "))
        assertNull(BackendUrl.normalize(null))
    }

    @Test
    fun malformedUrlsAreRejected() {
        assertNull(BackendUrl.normalize("not-a-url"))
        assertNull(BackendUrl.normalize("http://"))
        assertNull(BackendUrl.normalize("://missing-scheme"))
        assertNull(BackendUrl.normalize("http:// space.example"))
    }

    @Test
    fun unsupportedSchemesAreRejected() {
        assertNull(BackendUrl.normalize("ftp://files.example"))
        assertNull(BackendUrl.normalize("javascript:alert(1)"))
        assertNull(BackendUrl.normalize("file:///etc/passwd"))
    }

    @Test
    fun resolveKeepsValidStoredUrl() {
        assertEquals(
            "https://backend.example",
            BackendUrl.resolve("https://backend.example/"),
        )
    }

    @Test
    fun resolveFallsBackOnInvalidStoredConfigWithoutThrowing() {
        assertEquals(BackendUrl.DEFAULT, BackendUrl.resolve("not-a-url"))
        assertEquals(BackendUrl.DEFAULT, BackendUrl.resolve(null))
        assertEquals(BackendUrl.DEFAULT, BackendUrl.resolve("   "))
    }

    @Test
    fun resolveHonoursExplicitFallback() {
        assertEquals(
            "http://10.0.0.2:8899",
            BackendUrl.resolve("bad url", fallback = "http://10.0.0.2:8899/"),
        )
    }
}
