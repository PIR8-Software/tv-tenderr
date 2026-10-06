package com.movieswipe

import com.google.gson.Gson
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.concurrent.TimeUnit

class ApiClient(private var baseUrl: String, private var apiToken: String = "") {
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

    fun setUrl(url: String) { baseUrl = url }
    fun setToken(token: String) { apiToken = token }
    fun getBaseUrl(): String = baseUrl

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

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                callback(null, e.message)
            }
            override fun onResponse(call: Call, response: Response) {
                response.use {
                    if (it.isSuccessful) {
                        val body = it.body?.string()
                        val movies = gson.fromJson(body, MoviesResponse::class.java)
                        callback(movies, null)
                    } else {
                        callback(null, "HTTP ${it.code}")
                    }
                }
            }
        })
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

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                callback(null, e.message)
            }
            override fun onResponse(call: Call, response: Response) {
                response.use {
                    if (it.isSuccessful) {
                        val body = it.body?.string()
                        val stats = gson.fromJson(body, StatsResponse::class.java)
                        callback(stats, null)
                    } else {
                        callback(null, "HTTP ${it.code}")
                    }
                }
            }
        })
    }

    fun getPosterUrl(movieId: Int): String {
        return "$baseUrl/api/poster/$movieId"
    }

    fun getCalendar(days: Int = 30, callback: (CalendarResponse?, String?) -> Unit) {
        val request = Request.Builder()
            .url("$baseUrl/api/calendar?days=$days")
            .get()
            .build()

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) { callback(null, e.message) }
            override fun onResponse(call: Call, response: Response) {
                response.use {
                    if (it.isSuccessful) {
                        val body = it.body?.string()
                        callback(gson.fromJson(body, CalendarResponse::class.java), null)
                    } else {
                        callback(null, "HTTP ${it.code}")
                    }
                }
            }
        })
    }

    fun getHistory(callback: (HistoryResponse?, String?) -> Unit) {
        val request = Request.Builder()
            .url("$baseUrl/api/history")
            .get()
            .build()

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                callback(null, e.message)
            }
            override fun onResponse(call: Call, response: Response) {
                response.use {
                    if (it.isSuccessful) {
                        val body = it.body?.string()
                        val history = gson.fromJson(body, HistoryResponse::class.java)
                        callback(history, null)
                    } else {
                        callback(null, "HTTP ${it.code}")
                    }
                }
            }
        })
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

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                callback(null, e.message)
            }
            override fun onResponse(call: Call, response: Response) {
                response.use {
                    if (it.isSuccessful) {
                        val body = it.body?.string()
                        val shows = gson.fromJson(body, ShowsResponse::class.java)
                        callback(shows, null)
                    } else {
                        callback(null, "HTTP ${it.code}")
                    }
                }
            }
        })
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

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                callback(null, e.message)
            }
            override fun onResponse(call: Call, response: Response) {
                response.use {
                    if (it.isSuccessful) {
                        val body = it.body?.string()
                        val history = gson.fromJson(body, HistoryResponse::class.java)
                        callback(history, null)
                    } else {
                        callback(null, "HTTP ${it.code}")
                    }
                }
            }
        })
    }

    // ==================== DISCOVER METHODS ====================

    fun getProviders(callback: (ProvidersResponse?, String?) -> Unit) {
        val request = Request.Builder()
            .url("$baseUrl/api/providers")
            .get()
            .build()

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) { callback(null, e.message) }
            override fun onResponse(call: Call, response: Response) {
                response.use {
                    if (it.isSuccessful) {
                        val body = it.body?.string()
                        callback(gson.fromJson(body, ProvidersResponse::class.java), null)
                    } else { callback(null, "HTTP ${it.code}") }
                }
            }
        })
    }

    fun discoverMovies(page: Int = 1, limit: Int = 20, providers: String = "", sortBy: String = "popularity.desc", callback: (DiscoverMoviesResponse?, String?) -> Unit) {
        val providersQuery = if (providers.isNotEmpty()) "&providers=${java.net.URLEncoder.encode(providers, "UTF-8")}" else ""
        val url = "$baseUrl/api/discover/movies?page=$page&limit=$limit&sort_by=${java.net.URLEncoder.encode(sortBy, "UTF-8")}$providersQuery"
        val request = Request.Builder().url(url).get().build()

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) { callback(null, e.message) }
            override fun onResponse(call: Call, response: Response) {
                response.use {
                    if (it.isSuccessful) {
                        val body = it.body?.string()
                        callback(gson.fromJson(body, DiscoverMoviesResponse::class.java), null)
                    } else { callback(null, "HTTP ${it.code}") }
                }
            }
        })
    }

    fun discoverShows(page: Int = 1, limit: Int = 20, providers: String = "", sortBy: String = "popularity.desc", callback: (DiscoverShowsResponse?, String?) -> Unit) {
        val providersQuery = if (providers.isNotEmpty()) "&providers=${java.net.URLEncoder.encode(providers, "UTF-8")}" else ""
        val url = "$baseUrl/api/discover/shows?page=$page&limit=$limit&sort_by=${java.net.URLEncoder.encode(sortBy, "UTF-8")}$providersQuery"
        val request = Request.Builder().url(url).get().build()

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) { callback(null, e.message) }
            override fun onResponse(call: Call, response: Response) {
                response.use {
                    if (it.isSuccessful) {
                        val body = it.body?.string()
                        callback(gson.fromJson(body, DiscoverShowsResponse::class.java), null)
                    } else { callback(null, "HTTP ${it.code}") }
                }
            }
        })
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

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) { callback(null, e.message) }
            override fun onResponse(call: Call, response: Response) {
                response.use {
                    if (it.isSuccessful) {
                        val body = it.body?.string()
                        callback(gson.fromJson(body, HistoryResponse::class.java), null)
                    } else { callback(null, "HTTP ${it.code}") }
                }
            }
        })
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

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) { callback(null, e.message) }
            override fun onResponse(call: Call, response: Response) {
                response.use {
                    if (it.isSuccessful) {
                        val body = it.body?.string()
                        val info = gson.fromJson(body, UpdateInfo::class.java)
                        if (info.error != null) {
                            callback(null, info.error)
                        } else {
                            callback(info, null)
                        }
                    } else {
                        callback(null, "HTTP ${it.code}")
                    }
                }
            }
        })
    }
}
