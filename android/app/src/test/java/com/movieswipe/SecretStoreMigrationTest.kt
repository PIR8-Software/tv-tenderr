package com.movieswipe

import android.content.SharedPreferences
import java.lang.reflect.Proxy
import org.junit.Assert.*
import org.junit.Test

class SecretStoreMigrationTest {
    private class Store(initial: Map<String, String> = emptyMap()) {
        val values = initial.toMutableMap()
        var durable = initial.toMap()
        var succeeds = true
        var commits = 0
        private fun editor(): SharedPreferences.Editor {
            val pending = mutableMapOf<String, String?>()
            return Proxy.newProxyInstance(SharedPreferences.Editor::class.java.classLoader,
                arrayOf(SharedPreferences.Editor::class.java)) { proxy, method, args ->
                when (method.name) {
                    "putString" -> { pending[args!![0] as String] = args[1] as String?; proxy }
                    "remove" -> { pending[args!![0] as String] = null; proxy }
                    "commit" -> {
                        commits++
                        pending.forEach { (key, value) -> if (value == null) values.remove(key) else values[key] = value }
                        if (succeeds) durable = values.toMap()
                        succeeds
                    }
                    else -> throw UnsupportedOperationException(method.name)
                }
            } as SharedPreferences.Editor
        }
        val prefs = Proxy.newProxyInstance(SharedPreferences::class.java.classLoader,
            arrayOf(SharedPreferences::class.java)) { _, method, args ->
            when (method.name) {
                "contains" -> values.containsKey(args!![0])
                "getString" -> values[args!![0]] ?: args[1]
                "edit" -> editor()
                else -> throw UnsupportedOperationException(method.name)
            }
        } as SharedPreferences
    }

    @Test fun failedCommitAndCachedRetryNeverDeleteOnlyDurableCopy() {
        val plain = Store(mapOf("api_token" to "synthetic-legacy"))
        val encrypted = Store()
        encrypted.succeeds = false
        repeat(2) {
            try {
                SecretStore.migrate(plain.prefs, encrypted.prefs)
                fail("Expected durable migration failure")
            } catch (_: IllegalStateException) { }
            assertEquals("synthetic-legacy", plain.durable["api_token"])
            assertFalse(encrypted.durable.containsKey("api_token"))
        }
        assertEquals(2, encrypted.commits)
        encrypted.succeeds = true
        SecretStore.migrate(plain.prefs, encrypted.prefs)
        assertEquals("synthetic-legacy", encrypted.durable["api_token"])
        assertFalse(plain.durable.containsKey("api_token"))
    }

    @Test fun newerEncryptedValueWinsAndPlainRemovalFailureIsRetryable() {
        val plain = Store(mapOf("api_token" to "synthetic-old"))
        val encrypted = Store(mapOf("api_token" to "synthetic-new"))
        plain.succeeds = false
        SecretStore.migrate(plain.prefs, encrypted.prefs)
        assertEquals("synthetic-old", plain.durable["api_token"])
        assertEquals("synthetic-new", encrypted.durable["api_token"])
    }
}
