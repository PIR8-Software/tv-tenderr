package com.movieswipe

import com.google.gson.Gson
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.concurrent.TimeUnit

class ApiClient(rawBaseUrl: String, private var apiToken: String = "") {
    // F5: the active endpoint is always a validated HTTP(S) URL. An invalid
    // candidate (constructor or setUrl) falls back to / retains the previous
    // valid configuration instead of crashing request construction later.
    private var baseUrl: String = BackendUrl.resolve(rawBaseUrl)

    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .addInterceptor { chain ->
            val token = apiToken.trim()
            val request = if (token.isEmpty()) {
                chain.request()
            } else {
                chain.request().newBuilder().header("Authorization", "Bearer $token").build()
            }
            chain.proceed(request)
        }
        .build()
    private val gson = Gson()

    fun setUrl(url: String) {
        BackendUrl.normalize(url)?.let { baseUrl = it }
    }

    fun setToken(token: String) { apiToken = token }
    fun getBaseUrl(): String = baseUrl

    // ==================== F6: CENTRALIZED DEFENSIVE PARSING ====================
    //
    // Every "successful" body goes through [parseBody]: malformed JSON, HTML,
    // JSON null, empty bodies and schema violations all become a typed failure
    // delivered through the ordinary callback exactly once. Exceptions thrown
    // by caller callback code are never caught here.

    private fun <T> enqueueParsed(request: Request, type: Class<T>, callback: (T?, String?) -> Unit) {
        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                callback(null, e.message ?: "Network error")
            }

            override fun onResponse(call: Call, response: Response) {
                val outcome: Pair<T?, String?> = response.use {
                    if (!it.isSuccessful) {
                        null to "HTTP ${it.code}"
                    } else {
                        val body = try {
                            it.body?.string()
                        } catch (e: IOException) {
                            null
                        }
                        parseBody(body, type)
                    }
                }
                callback(outcome.first, outcome.second)
            }
        })
    }

    private fun <T> parseBody(body: String?, type: Class<T>): Pair<T?, String?> {
        if (body.isNullOrBlank()) return null to "Empty server response"
        val parsed: T? = try {
            gson.fromJson(body, type)
        } catch (e: RuntimeException) {
            // Malformed payloads (bad JSON, HTML, type mismatches) must not
            // escape onto the OkHttp callback thread.
            null
        }
        if (parsed == null || !isSchemaValid(parsed)) return null to "Invalid server response"
        return parsed to null
    }

    @Suppress("SENSELESS_COMPARISON")
    private fun isSchemaValid(value: Any): Boolean = when (value) {
        is MoviesResponse -> value.movies != null && value.movies.all { it.title != null }
        is ShowsResponse -> value.shows != null && value.shows.all { it.title != null }
        is HistoryResponse -> value.history != null
        is CalendarResponse -> value.calendar != null
        is DiscoverMoviesResponse -> value.movies != null && value.movies.all { it.title != null }
        is DiscoverShowsResponse -> value.shows != null && value.shows.all { it.title != null }
        is ProvidersResponse -> value.movie_providers != null && value.tv_providers != null
        is StatsResponse -> value.movies != null && value.shows != null && value.discover != null
        else -> true
    }

    // ==================== MOVIE METHODS ====================

    fun refreshPlex(callback: (Boolean, String?) -> Unit) {
        val request = Request.Builder()
            .url("$baseUrl/api/plex/refresh")
            .post(ByteArray(0).toRequestBody(null))
            .build()

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                callback(false, e.message)
            }
            override fun onResponse(call: Call, response: Response) {
                response.use {
                    callback(it.isSuccessful, if (it.isSuccessful) null else "HTTP ${it.code}")
                }
            }
        })
    }

    fun getMovies(skip: Int = 0, limit: Int = 20, genre: String = "", minYear: Int = 0, maxYear: Int = 0, minRating: Float = 0f, search: String = "", callback: (MoviesResponse?, String?) -> Unit) {
        val request = Request.Builder()
            .url(buildString {
                append("$baseUrl/api/movies?skip=$skip&limit=$limit")
                if (genre.isNotBlank()) append("&genre=${java.net.URLEncoder.encode(genre, "UTF-8")}")
                if (minYear > 0) append("&min_year=$minYear")
                if (maxYear > 0) append("&max_year=$maxYear")
                if (minRating > 0f) append("&min_rating=$minRating")
                if (search.isNotBlank()) append("&search=${java.net.URLEncoder.encode(search, "UTF-8")}")
            })
            .get()
            .build()

        enqueueParsed(request, MoviesResponse::class.java, callback)
    }

    fun keepMovie(movieId: Int, callback: (Boolean, String?) -> Unit) {
        postAction(movieId, "keep", callback)
    }

    fun superKeepMovie(movieId: Int, callback: (Boolean, String?) -> Unit) {
        postAction(movieId, "super_keep", callback)
    }

    fun blockMovie(movieId: Int, callback: (Boolean, String?) -> Unit) {
        postAction(movieId, "block", callback)
    }

    fun skipMovie(movieId: Int, callback: (Boolean, String?) -> Unit) {
        postAction(movieId, "skip", callback)
    }

    private fun postAction(movieId: Int, action: String, callback: (Boolean, String?) -> Unit) {
        val request = Request.Builder()
            .url("$baseUrl/api/movies/$movieId/$action")
            .post(ByteArray(0).toRequestBody(null))
            .build()

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                callback(false, e.message)
            }
            override fun onResponse(call: Call, response: Response) {
                response.use {
                    callback(it.isSuccessful, if (it.isSuccessful) null else "HTTP ${it.code}")
                }
            }
        })
    }

    fun getStats(callback: (StatsResponse?, String?) -> Unit) {
        val request = Request.Builder()
            .url("$baseUrl/api/stats")
            .get()
            .build()
        enqueueParsed(request, StatsResponse::class.java, callback)
    }

    fun getPosterUrl(movieId: Int): String {
        return "$baseUrl/api/poster/$movieId"
    }

    fun getCalendar(days: Int = 30, callback: (CalendarResponse?, String?) -> Unit) {
        val request = Request.Builder()
            .url("$baseUrl/api/calendar?days=$days")
            .get()
            .build()
        enqueueParsed(request, CalendarResponse::class.java, callback)
    }

    fun getHistory(callback: (HistoryResponse?, String?) -> Unit) {
        val request = Request.Builder()
            .url("$baseUrl/api/history")
            .get()
            .build()
        enqueueParsed(request, HistoryResponse::class.java, callback)
    }

    fun unkeepMovie(movieId: Int, callback: (Boolean, String?) -> Unit) {
        postAction(movieId, "unkeep", callback)
    }

    fun unblockMovie(movieId: Int, callback: (Boolean, String?) -> Unit) {
        postAction(movieId, "unblock", callback)
    }

    // ==================== SHOW METHODS ====================

    fun getShows(skip: Int = 0, limit: Int = 20, genre: String = "", minYear: Int = 0, maxYear: Int = 0, minRating: Float = 0f, search: String = "", callback: (ShowsResponse?, String?) -> Unit) {
        val request = Request.Builder()
            .url(buildString {
                append("$baseUrl/api/shows?skip=$skip&limit=$limit")
                if (genre.isNotBlank()) append("&genre=${java.net.URLEncoder.encode(genre, "UTF-8")}")
                if (minYear > 0) append("&min_year=$minYear")
                if (maxYear > 0) append("&max_year=$maxYear")
                if (minRating > 0f) append("&min_rating=$minRating")
                if (search.isNotBlank()) append("&search=${java.net.URLEncoder.encode(search, "UTF-8")}")
            })
            .get()
            .build()

        enqueueParsed(request, ShowsResponse::class.java, callback)
    }

    fun postShowAction(showId: Int, action: String, callback: (Boolean, String?) -> Unit) {
        val request = Request.Builder()
            .url("$baseUrl/api/shows/$showId/$action")
            .post(ByteArray(0).toRequestBody(null))
            .build()

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                callback(false, e.message)
            }
            override fun onResponse(call: Call, response: Response) {
                response.use {
                    callback(it.isSuccessful, if (it.isSuccessful) null else "HTTP ${it.code}")
                }
            }
        })
    }

    fun keepShow(showId: Int, callback: (Boolean, String?) -> Unit) {
        postShowAction(showId, "keep", callback)
    }

    fun superKeepShow(showId: Int, callback: (Boolean, String?) -> Unit) {
        postShowAction(showId, "super_keep", callback)
    }

    fun blockShow(showId: Int, callback: (Boolean, String?) -> Unit) {
        postShowAction(showId, "block", callback)
    }

    fun skipShow(showId: Int, callback: (Boolean, String?) -> Unit) {
        postShowAction(showId, "skip", callback)
    }

    fun cleanShow(showId: Int, callback: (Boolean, String?) -> Unit) {
        postShowAction(showId, "clean", callback)
    }

    fun uncleanShow(showId: Int, callback: (Boolean, String?) -> Unit) {
        postShowAction(showId, "unclean", callback)
    }

    fun getShowHistory(callback: (HistoryResponse?, String?) -> Unit) {
        val request = Request.Builder()
            .url("$baseUrl/api/shows/history")
            .get()
            .build()
        enqueueParsed(request, HistoryResponse::class.java, callback)
    }

    // ==================== DISCOVER METHODS ====================

    fun getProviders(callback: (ProvidersResponse?, String?) -> Unit) {
        val request = Request.Builder()
            .url("$baseUrl/api/providers")
            .get()
            .build()
        enqueueParsed(request, ProvidersResponse::class.java, callback)
    }

    fun discoverMovies(page: Int = 1, limit: Int = 20, providers: String = "", sortBy: String = "popularity.desc", callback: (DiscoverMoviesResponse?, String?) -> Unit) {
        val providersQuery = if (providers.isNotEmpty()) "&providers=${java.net.URLEncoder.encode(providers, "UTF-8")}" else ""
        val url = "$baseUrl/api/discover/movies?page=$page&limit=$limit&sort_by=${java.net.URLEncoder.encode(sortBy, "UTF-8")}$providersQuery"
        val request = Request.Builder().url(url).get().build()
        enqueueParsed(request, DiscoverMoviesResponse::class.java, callback)
    }

    fun discoverShows(page: Int = 1, limit: Int = 20, providers: String = "", sortBy: String = "popularity.desc", callback: (DiscoverShowsResponse?, String?) -> Unit) {
        val providersQuery = if (providers.isNotEmpty()) "&providers=${java.net.URLEncoder.encode(providers, "UTF-8")}" else ""
        val url = "$baseUrl/api/discover/shows?page=$page&limit=$limit&sort_by=${java.net.URLEncoder.encode(sortBy, "UTF-8")}$providersQuery"
        val request = Request.Builder().url(url).get().build()
        enqueueParsed(request, DiscoverShowsResponse::class.java, callback)
    }

    fun dislikeDiscover(tmdbId: Int, title: String? = null, year: String? = null, posterUrl: String? = null, type: String = "movie", callback: (Boolean, String?) -> Unit = { _, _ -> }) {
        val bodyMap = mutableMapOf<String, Any>()
        title?.let { bodyMap["title"] = it }
        year?.let { bodyMap["year"] = it }
        posterUrl?.let { bodyMap["posterUrl"] = it }
        bodyMap["type"] = type

        val json = gson.toJson(bodyMap)
        val body = json.toRequestBody("application/json".toMediaType())
        val request = Request.Builder()
            .url("$baseUrl/api/discover/$tmdbId/dislike")
            .post(body)
            .build()

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) { callback(false, e.message) }
            override fun onResponse(call: Call, response: Response) {
                response.use { callback(it.isSuccessful, if (it.isSuccessful) null else "HTTP ${it.code}") }
            }
        })
    }

    fun hideDiscover(tmdbId: Int, title: String? = null, year: String? = null, posterUrl: String? = null, type: String = "movie", callback: (Boolean, String?) -> Unit = { _, _ -> }) {
        val bodyMap = mutableMapOf<String, Any>("action" to "hidden")
        title?.let { bodyMap["title"] = it }
        year?.let { bodyMap["year"] = it }
        posterUrl?.let { bodyMap["posterUrl"] = it }
        bodyMap["type"] = type

        val json = gson.toJson(bodyMap)
        val body = json.toRequestBody("application/json".toMediaType())
        val request = Request.Builder()
            .url("$baseUrl/api/discover/$tmdbId/hide")
            .post(body)
            .build()

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) { callback(false, e.message) }
            override fun onResponse(call: Call, response: Response) {
                response.use { callback(it.isSuccessful, if (it.isSuccessful) null else "HTTP ${it.code}") }
            }
        })
    }

    fun addMovieFromDiscover(tmdbId: Int, callback: (Boolean, String?) -> Unit) {
        val request = Request.Builder()
            .url("$baseUrl/api/discover/$tmdbId/add_movie")
            .post(ByteArray(0).toRequestBody(null))
            .build()

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) { callback(false, e.message) }
            override fun onResponse(call: Call, response: Response) {
                response.use { callback(it.isSuccessful, if (it.isSuccessful) null else "HTTP ${it.code}") }
            }
        })
    }

    fun addShowFromDiscover(tmdbId: Int, callback: (Boolean, String?) -> Unit) {
        val request = Request.Builder()
            .url("$baseUrl/api/discover/$tmdbId/add_show")
            .post(ByteArray(0).toRequestBody(null))
            .build()

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) { callback(false, e.message) }
            override fun onResponse(call: Call, response: Response) {
                response.use { callback(it.isSuccessful, if (it.isSuccessful) null else "HTTP ${it.code}") }
            }
        })
    }

    fun getDiscoverHistory(callback: (HistoryResponse?, String?) -> Unit) {
        val request = Request.Builder()
            .url("$baseUrl/api/discover/history")
            .get()
            .build()
        enqueueParsed(request, HistoryResponse::class.java, callback)
    }

    fun unhideDiscover(tmdbId: Int, callback: (Boolean, String?) -> Unit) {
        val request = Request.Builder()
            .url("$baseUrl/api/discover/$tmdbId/unhide")
            .post(ByteArray(0).toRequestBody(null))
            .build()

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) { callback(false, e.message) }
            override fun onResponse(call: Call, response: Response) {
                response.use { callback(it.isSuccessful, if (it.isSuccessful) null else "HTTP ${it.code}") }
            }
        })
    }

    fun removeMovieFromDiscover(tmdbId: Int, callback: (Boolean, String?) -> Unit) {
        val request = Request.Builder()
            .url("$baseUrl/api/discover/$tmdbId/remove_movie")
            .post(ByteArray(0).toRequestBody(null))
            .build()

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) { callback(false, e.message) }
            override fun onResponse(call: Call, response: Response) {
                response.use { callback(it.isSuccessful, if (it.isSuccessful) null else "HTTP ${it.code}") }
            }
        })
    }

    fun removeShowFromDiscover(tmdbId: Int, callback: (Boolean, String?) -> Unit) {
        val request = Request.Builder()
            .url("$baseUrl/api/discover/$tmdbId/remove_show")
            .post(ByteArray(0).toRequestBody(null))
            .build()

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) { callback(false, e.message) }
            override fun onResponse(call: Call, response: Response) {
                response.use { callback(it.isSuccessful, if (it.isSuccessful) null else "HTTP ${it.code}") }
            }
        })
    }

    // ==================== UPDATE CHECK ====================

    fun checkForUpdates(callback: (UpdateInfo?, String?) -> Unit) {
        val request = Request.Builder()
            .url("$baseUrl/api/latest-release")
            .get()
            .build()
        enqueueParsed(request, UpdateInfo::class.java) { info, error ->
            when {
                error != null -> callback(null, error)
                info == null -> callback(null, "Invalid server response")
                info.error != null -> callback(null, info.error)
                else -> callback(info, null)
            }
        }
    }
}
