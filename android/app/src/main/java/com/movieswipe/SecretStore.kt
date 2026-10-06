package com.movieswipe

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKeys

object SecretStore {
    const val FILE_NAME = "movieswipe_secrets"

    fun open(context: Context): SharedPreferences {
        val masterKeyAlias = MasterKeys.getOrCreate(MasterKeys.AES256_GCM_SPEC)
        val encrypted = EncryptedSharedPreferences.create(
            FILE_NAME,
            masterKeyAlias,
            context,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
        val plain = context.getSharedPreferences("movieswipe", Context.MODE_PRIVATE)
        migrate(plain, encrypted)
        return encrypted
    }

    fun migrate(plain: SharedPreferences, encrypted: SharedPreferences) {
        if (SECRET_PREF_KEYS.none { plain.contains(it) }) return
        val plainValues = SECRET_PREF_KEYS.associateWith { plain.getString(it, null) }
        val encryptedValues = SECRET_PREF_KEYS.associateWith { encrypted.getString(it, null) }
        val merged = migratedSecrets(plainValues, encryptedValues)
        val editor = encrypted.edit()
        for ((key, value) in merged) editor.putString(key, value)
        // A failed commit may still update SharedPreferences' cached in-memory map.
        // Always retry the durable commit while plaintext remains, even if the
        // values now compare equal; otherwise a retry could delete the only copy.
        if (!editor.commit()) throw IllegalStateException("Secret migration could not be persisted")
        val after = SECRET_PREF_KEYS.associateWith { encrypted.getString(it, null).orEmpty() }
        val remove = plaintextSecretsToRemove(plainValues, after)
        if (remove.isNotEmpty()) {
            val plainEditor = plain.edit()
            remove.forEach(plainEditor::remove)
            plainEditor.commit()
        }
    }
}

fun storedApiToken(context: Context): String =
    try {
        SecretStore.open(context).getString("api_token", "") ?: ""
    } catch (_: Exception) {
        ""
    }
