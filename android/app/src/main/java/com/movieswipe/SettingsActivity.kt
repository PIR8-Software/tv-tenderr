package com.movieswipe

import android.os.Bundle
import android.widget.ArrayAdapter
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.movieswipe.databinding.ActivitySettingsBinding
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException

class SettingsActivity : AppCompatActivity() {

    private lateinit var binding: ActivitySettingsBinding
    private lateinit var api: ApiClient
    private val radarrProfiles = mutableListOf<Pair<Int, String>>()
    private val sonarrProfiles = mutableListOf<Pair<Int, String>>()
    private val radarrRoots = mutableListOf<String>()
    private val sonarrRoots = mutableListOf<String>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivitySettingsBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val prefs = getSharedPreferences("movieswipe", MODE_PRIVATE)
        val secrets = SecretStore.open(this)
        val serverUrl = prefs.getString("server_url", "http://localhost:8899") ?: "http://localhost:8899"
        val apiToken = secrets.getString("api_token", "") ?: ""
        api = ApiClient(serverUrl, apiToken)

        // Load saved settings. Secrets come from encrypted storage, never from the backup-eligible file.
        binding.etBackendUrl.setText(serverUrl)
        binding.etApiToken.setText(apiToken)
        binding.etRadarrUrl.setText(prefs.getString("radarr_url", "http://localhost:7878"))
        binding.etRadarrKey.setText(secrets.getString("radarr_key", "") ?: "")
        binding.etSonarrUrl.setText(prefs.getString("sonarr_url", "http://localhost:8989"))
        binding.etSonarrKey.setText(secrets.getString("sonarr_key", "") ?: "")
        binding.etPlexUrl.setText(prefs.getString("plex_url", "http://localhost:32400"))
        binding.etPlexToken.setText(secrets.getString("plex_token", "") ?: "")
        binding.etTmdbKey.setText(secrets.getString("tmdb_key", "") ?: "")

        // Load quality/root options from backend
        loadQualityProfiles(serverUrl)

        binding.btnBack.setOnClickListener { finish() }

        // Version info and update check
        val versionName = try {
            packageManager.getPackageInfo(packageName, 0).versionName ?: "1.0"
        } catch (e: Exception) { "1.0" }
        binding.tvCurrentVersion.text = "v$versionName"

        binding.btnCheckUpdates.setOnClickListener {
            binding.tvUpdateStatus.text = "Checking..."
            binding.tvUpdateStatus.setTextColor(android.graphics.Color.parseColor("#8B949E"))
            api.checkForUpdates { info, error ->
                runOnUiThread {
                    if (error != null) {
                        binding.tvUpdateStatus.text = "Check failed"
                        binding.tvUpdateStatus.setTextColor(android.graphics.Color.parseColor("#e74c3c"))
                    } else if (info != null) {
                        val latestVersion = info.version ?: "0"
                        if (isNewerVersion(latestVersion, versionName)) {
                            binding.tvUpdateStatus.text = "⬆ Update available: v${info.version}"
                            binding.tvUpdateStatus.setTextColor(android.graphics.Color.parseColor("#2ecc71"))
                            binding.tvUpdateStatus.setOnClickListener {
                                val intent = android.content.Intent(android.content.Intent.ACTION_VIEW,
                                    android.net.Uri.parse(info.htmlUrl ?: "https://github.com/PIR8-Software/tv-tenderr/releases/latest"))
                                startActivity(intent)
                            }
                        } else {
                            binding.tvUpdateStatus.text = "✓ You're on the latest version"
                            binding.tvUpdateStatus.setTextColor(android.graphics.Color.parseColor("#8B949E"))
                            binding.tvUpdateStatus.setOnClickListener(null)
                        }
                    }
                }
            }
        }

        binding.btnSave.setOnClickListener {
            val editor = prefs.edit()
            editor.putString("server_url", binding.etBackendUrl.text.toString().trim())
            editor.putString("radarr_url", binding.etRadarrUrl.text.toString().trim())
            editor.putString("sonarr_url", binding.etSonarrUrl.text.toString().trim())
            editor.putString("plex_url", binding.etPlexUrl.text.toString().trim())
            editor.remove("radarr_key")
            editor.remove("sonarr_key")
            editor.remove("plex_token")
            editor.remove("tmdb_key")
            editor.remove("api_token")

            var radarrQualityId: Int? = null
            var sonarrQualityId: Int? = null
            var radarrRoot: String? = null
            var sonarrRoot: String? = null
            val radarrQualityPos = binding.spinnerRadarrQuality.selectedItemPosition
            if (radarrQualityPos >= 0 && radarrQualityPos < radarrProfiles.size) {
                val selectedId = radarrProfiles[radarrQualityPos].first
                radarrQualityId = selectedId
                editor.putInt("radarr_quality_id", selectedId)
                editor.putString("radarr_quality_name", radarrProfiles[radarrQualityPos].second)
            }

            val sonarrQualityPos = binding.spinnerSonarrQuality.selectedItemPosition
            if (sonarrQualityPos >= 0 && sonarrQualityPos < sonarrProfiles.size) {
                val selectedId = sonarrProfiles[sonarrQualityPos].first
                sonarrQualityId = selectedId
                editor.putInt("sonarr_quality_id", selectedId)
                editor.putString("sonarr_quality_name", sonarrProfiles[sonarrQualityPos].second)
            }

            val radarrRootPos = binding.spinnerRadarrRoot.selectedItemPosition
            if (radarrRootPos >= 0 && radarrRootPos < radarrRoots.size) {
                radarrRoot = radarrRoots[radarrRootPos]
                editor.putString("radarr_root", radarrRoot)
            }

            val sonarrRootPos = binding.spinnerSonarrRoot.selectedItemPosition
            if (sonarrRootPos >= 0 && sonarrRootPos < sonarrRoots.size) {
                sonarrRoot = sonarrRoots[sonarrRootPos]
                editor.putString("sonarr_root", sonarrRoot)
            }

            editor.apply()
            val secretEditor = secrets.edit()
            configuredSetting(binding.etRadarrKey.text.toString(), "YOUR_RADARR_API_KEY")?.let { secretEditor.putString("radarr_key", it) }
            configuredSetting(binding.etSonarrKey.text.toString(), "YOUR_SONARR_API_KEY")?.let { secretEditor.putString("sonarr_key", it) }
            configuredSetting(binding.etPlexToken.text.toString(), "YOUR_PLEX_TOKEN")?.let { secretEditor.putString("plex_token", it) }
            configuredSetting(binding.etTmdbKey.text.toString(), "YOUR_TMDB_KEY")?.let { secretEditor.putString("tmdb_key", it) }
            configuredSetting(binding.etApiToken.text.toString(), "")?.let { secretEditor.putString("api_token", it) }
            secretEditor.apply()

            val config = settingsConfigPayload(
                values = mapOf(
                    "radarrUrl" to binding.etRadarrUrl.text.toString(),
                    "radarrKey" to binding.etRadarrKey.text.toString(),
                    "sonarrUrl" to binding.etSonarrUrl.text.toString(),
                    "sonarrKey" to binding.etSonarrKey.text.toString(),
                    "plexUrl" to binding.etPlexUrl.text.toString(),
                    "plexToken" to binding.etPlexToken.text.toString(),
                    "tmdbKey" to binding.etTmdbKey.text.toString(),
                ),
                defaults = mapOf(
                    "radarrUrl" to "http://localhost:7878",
                    "radarrKey" to "YOUR_RADARR_API_KEY",
                    "sonarrUrl" to "http://localhost:8989",
                    "sonarrKey" to "YOUR_SONARR_API_KEY",
                    "plexUrl" to "http://localhost:32400",
                    "plexToken" to "YOUR_PLEX_TOKEN",
                    "tmdbKey" to "YOUR_TMDB_KEY",
                ),
                radarrQualityId = radarrQualityId,
                sonarrQualityId = sonarrQualityId,
                radarrRoot = radarrRoot,
                sonarrRoot = sonarrRoot,
            )
            val token = binding.etApiToken.text.toString().trim().ifEmpty { secrets.getString("api_token", "").orEmpty() }
            api.setUrl(binding.etBackendUrl.text.toString().trim())
            api.setToken(token)

            val client = OkHttpClient()
            val json = com.google.gson.Gson().toJson(config)
            val body = json.toRequestBody("application/json".toMediaType())
            val requestBuilder = Request.Builder()
                .url("${binding.etBackendUrl.text.toString().trim()}/api/config")
                .post(body)
            if (token.isNotEmpty()) requestBuilder.header("Authorization", "Bearer $token")
            val request = requestBuilder.build()

            client.newCall(request).enqueue(object : Callback {
                override fun onFailure(call: Call, e: IOException) {
                    runOnUiThread { binding.tvStatus.text = "Saved locally (backend unreachable)" }
                }
                override fun onResponse(call: Call, response: Response) {
                    val message = settingsSaveMessage(response.isSuccessful)
                    runOnUiThread {
                        binding.tvStatus.text = message
                        if (response.isSuccessful) loadQualityProfiles(binding.etBackendUrl.text.toString().trim())
                        Toast.makeText(this@SettingsActivity, message, Toast.LENGTH_SHORT).show()
                    }
                    response.close()
                }
            })
        }
    }

    private fun loadQualityProfiles(serverUrl: String) {
        val client = OkHttpClient()
        val requestBuilder = Request.Builder()
            .url("$serverUrl/api/config")
            .get()
        val token = binding.etApiToken.text.toString().trim()
        if (token.isNotEmpty()) requestBuilder.header("Authorization", "Bearer $token")
        val request = requestBuilder.build()

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {}
            override fun onResponse(call: Call, response: Response) {
                response.use {
                    if (it.isSuccessful) {
                        val body = it.body?.string()
                        val config = com.google.gson.Gson().fromJson(body, Map::class.java) as Map<*, *>
                        val radarrUrl = config["radarrUrl"]?.toString() ?: return@use
                        val sonarrUrl = config["sonarrUrl"]?.toString() ?: return@use

                        runOnUiThread {
                            binding.etRadarrUrl.setText(preferBackendSetting(binding.etRadarrUrl.text.toString(), radarrUrl, "http://localhost:7878"))
                            binding.etSonarrUrl.setText(preferBackendSetting(binding.etSonarrUrl.text.toString(), sonarrUrl, "http://localhost:8989"))
                            binding.etPlexUrl.setText(preferBackendSetting(binding.etPlexUrl.text.toString(), config["plexUrl"]?.toString() ?: "", "http://localhost:32400"))
                        }
                        fetchBackendOptions(serverUrl)
                    }
                }
            }
        })
    }

    private fun fetchBackendOptions(serverUrl: String) {
        val client = OkHttpClient()
        val requestBuilder = Request.Builder()
            .url("$serverUrl/api/config/options")
        val token = binding.etApiToken.text.toString().trim()
        if (token.isNotEmpty()) requestBuilder.header("Authorization", "Bearer $token")
        val request = requestBuilder.build()

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {}
            override fun onResponse(call: Call, response: Response) {
                response.use {
                    if (it.isSuccessful) {
                        val body = it.body?.string()
                        val options = com.google.gson.Gson().fromJson(body, BackendOptions::class.java)
                        runOnUiThread {
                            radarrProfiles.clear()
                            radarrProfiles.addAll(options.radarrProfiles.map { Pair(it.id, it.name) })
                            sonarrProfiles.clear()
                            sonarrProfiles.addAll(options.sonarrProfiles.map { Pair(it.id, it.name) })
                            radarrRoots.clear()
                            radarrRoots.addAll(options.radarrRoots)
                            sonarrRoots.clear()
                            sonarrRoots.addAll(options.sonarrRoots)

                            binding.spinnerRadarrQuality.adapter = spinnerAdapter(radarrProfiles.map { it.second })
                            binding.spinnerSonarrQuality.adapter = spinnerAdapter(sonarrProfiles.map { it.second })
                            binding.spinnerRadarrRoot.adapter = spinnerAdapter(radarrRoots)
                            binding.spinnerSonarrRoot.adapter = spinnerAdapter(sonarrRoots)

                            selectSavedProfile(binding.spinnerRadarrQuality, radarrProfiles, "radarr_quality_id")
                            selectSavedProfile(binding.spinnerSonarrQuality, sonarrProfiles, "sonarr_quality_id")
                            selectSavedRoot(binding.spinnerRadarrRoot, radarrRoots, "radarr_root", "H:\\")
                            selectSavedRoot(binding.spinnerSonarrRoot, sonarrRoots, "sonarr_root", "I:\\TV")
                        }
                    }
                }
            }
        })
    }

    private fun spinnerAdapter(values: List<String>): ArrayAdapter<String> =
        ArrayAdapter(this, android.R.layout.simple_spinner_item, values).also {
            it.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
        }

    private fun selectSavedProfile(spinner: android.widget.Spinner, profiles: List<Pair<Int, String>>, key: String) {
        val savedId = getSharedPreferences("movieswipe", MODE_PRIVATE).getInt(key, 4)
        profiles.indexOfFirst { it.first == savedId }.takeIf { it >= 0 }?.let(spinner::setSelection)
    }

    private fun selectSavedRoot(spinner: android.widget.Spinner, roots: List<String>, key: String, fallback: String) {
        val saved = getSharedPreferences("movieswipe", MODE_PRIVATE).getString(key, fallback)
        roots.indexOf(saved).takeIf { it >= 0 }?.let(spinner::setSelection)
    }
}

data class QualityProfile(val id: Int, val name: String)
data class BackendOptions(
    val radarrProfiles: List<QualityProfile>,
    val radarrRoots: List<String>,
    val sonarrProfiles: List<QualityProfile>,
    val sonarrRoots: List<String>,
)

private fun isNewerVersion(latest: String, current: String): Boolean {
    val latestParts = latest.split(".").map { it.toIntOrNull() ?: 0 }
    val currentParts = current.split(".").map { it.toIntOrNull() ?: 0 }
    val maxLen = maxOf(latestParts.size, currentParts.size)
    for (i in 0 until maxLen) {
        val l = latestParts.getOrElse(i) { 0 }
        val c = currentParts.getOrElse(i) { 0 }
        if (l > c) return true
        if (l < c) return false
    }
    return false
}
