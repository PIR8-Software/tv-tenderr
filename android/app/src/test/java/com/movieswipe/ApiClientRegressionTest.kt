package com.movieswipe

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class ApiClientRegressionTest {
    private lateinit var server: MockWebServer
    private lateinit var api: ApiClient

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
        api = ApiClient(server.url("").toString().removeSuffix("/"))
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    @Test
    fun showSearchAndFiltersAreSentToBackend() {
        server.enqueue(MockResponse().setResponseCode(200).setBody("{\"shows\":[],\"total\":0}"))
        val callback = CountDownLatch(1)
        var error: String? = null

        api.getShows(
            skip = 20,
            limit = 10,
            genre = "Science Fiction",
            minYear = 2000,
            maxYear = 2025,
            minRating = 7.5f,
            search = "star trek",
        ) { _, failure ->
            error = failure
            callback.countDown()
        }

        assertTrue(callback.await(2, TimeUnit.SECONDS))
        assertNull(error)
        assertEquals(
            "/api/shows?skip=20&limit=10&genre=Science+Fiction&min_year=2000&max_year=2025&min_rating=7.5&search=star+trek",
            server.takeRequest(2, TimeUnit.SECONDS)!!.path,
        )
    }

    @Test
    fun allRemainingAppActionsPostToExpectedEndpoints() {
        val actions = listOf<Pair<String, ((Boolean, String?) -> Unit) -> Unit>>(
            "/api/movies/11/keep" to { callback -> api.keepMovie(11, callback) },
            "/api/movies/11/super_keep" to { callback -> api.superKeepMovie(11, callback) },
            "/api/movies/11/block" to { callback -> api.blockMovie(11, callback) },
            "/api/movies/11/skip" to { callback -> api.skipMovie(11, callback) },
            "/api/shows/22/keep" to { callback -> api.keepShow(22, callback) },
            "/api/shows/22/super_keep" to { callback -> api.superKeepShow(22, callback) },
            "/api/shows/22/block" to { callback -> api.blockShow(22, callback) },
            "/api/shows/22/skip" to { callback -> api.skipShow(22, callback) },
            "/api/shows/22/clean" to { callback -> api.cleanShow(22, callback) },
            "/api/discover/33/add_movie" to { callback -> api.addMovieFromDiscover(33, callback) },
            "/api/discover/44/add_show" to { callback -> api.addShowFromDiscover(44, callback) },
            "/api/discover/55/hide" to { callback -> api.hideDiscover(55, callback = callback) },
            "/api/discover/66/dislike" to { callback -> api.dislikeDiscover(66, callback = callback) },
            "/api/plex/refresh" to { callback -> api.refreshPlex(callback) },
        )

        actions.forEach { (expectedPath, invoke) ->
            server.enqueue(MockResponse().setResponseCode(200).setBody("{\"ok\":true}"))
            val callback = CountDownLatch(1)
            var succeeded = false
            invoke { ok, _ ->
                succeeded = ok
                callback.countDown()
            }
            assertTrue(callback.await(2, TimeUnit.SECONDS))
            assertTrue(succeeded)
            val request = server.takeRequest(2, TimeUnit.SECONDS)!!
            assertEquals("POST", request.method)
            assertEquals(expectedPath, request.path)
        }
    }

    @Test
    fun filteredMoviesUseExpectedQueryParameters() {
        server.enqueue(MockResponse().setResponseCode(200).setBody("{\"movies\":[],\"total\":0}"))
        val callback = CountDownLatch(1)
        api.getMovies(10, 5, "Action", 1990, 2026, 8f, "test movie") { _, _ -> callback.countDown() }
        assertTrue(callback.await(2, TimeUnit.SECONDS))
        assertEquals(
            "/api/movies?skip=10&limit=5&genre=Action&min_year=1990&max_year=2026&min_rating=8.0&search=test+movie",
            server.takeRequest(2, TimeUnit.SECONDS)!!.path,
        )
    }

    @Test
    fun calendarProvidersDiscoverStatsAndUpdateUseExpectedEndpoints() {
        val cases = listOf<Pair<String, (CountDownLatch) -> Unit>>(
            "/api/calendar?days=90" to { latch ->
                server.enqueue(MockResponse().setResponseCode(200).setBody("{\"calendar\":[],\"total\":0}"))
                api.getCalendar(90) { _, _ -> latch.countDown() }
            },
            "/api/providers" to { latch ->
                server.enqueue(MockResponse().setResponseCode(200).setBody("{\"movie_providers\":[],\"tv_providers\":[]}"))
                api.getProviders { _, _ -> latch.countDown() }
            },
            "/api/discover/movies?page=2&limit=15&sort_by=vote_average.desc&providers=8%7C9" to { latch ->
                server.enqueue(MockResponse().setResponseCode(200).setBody("{\"movies\":[],\"total\":0,\"page\":2}"))
                api.discoverMovies(2, 15, "8|9", "vote_average.desc") { _, _ -> latch.countDown() }
            },
            "/api/discover/shows?page=3&limit=10&sort_by=release_date.desc&providers=337" to { latch ->
                server.enqueue(MockResponse().setResponseCode(200).setBody("{\"shows\":[],\"total\":0,\"page\":3}"))
                api.discoverShows(3, 10, "337", "release_date.desc") { _, _ -> latch.countDown() }
            },
            "/api/stats" to { latch ->
                server.enqueue(MockResponse().setResponseCode(200).setBody("{\"movies\":{\"total\":0,\"kept\":0,\"superKept\":0,\"blocked\":0,\"skipped\":0,\"undecided\":0},\"shows\":{\"total\":0,\"kept\":0,\"superKept\":0,\"blocked\":0,\"skipped\":0,\"undecided\":0},\"discover\":{\"added\":0,\"hidden\":0}}"))
                api.getStats { _, _ -> latch.countDown() }
            },
            "/api/latest-release" to { latch ->
                server.enqueue(MockResponse().setResponseCode(200).setBody("{\"version\":\"1.3.1\"}"))
                api.checkForUpdates { _, _ -> latch.countDown() }
            },
        )

        cases.forEach { (expectedPath, invoke) ->
            val callback = CountDownLatch(1)
            invoke(callback)
            assertTrue(callback.await(2, TimeUnit.SECONDS))
            assertEquals(expectedPath, server.takeRequest(2, TimeUnit.SECONDS)!!.path)
        }
    }

    @Test
    fun failedActionsReturnFalseAndHttpError() {
        server.enqueue(MockResponse().setResponseCode(503).setBody("unavailable"))
        val callback = CountDownLatch(1)
        var succeeded = true
        var error: String? = null
        api.keepMovie(11) { ok, failure ->
            succeeded = ok
            error = failure
            callback.countDown()
        }
        assertTrue(callback.await(2, TimeUnit.SECONDS))
        assertFalse(succeeded)
        assertEquals("HTTP 503", error)
    }

    @Test
    fun bearerTokenIsSentWhenConfiguredAndOmittedWhenBlank() {
        api.setToken("synthetic-test-token")
        server.enqueue(MockResponse().setResponseCode(200).setBody("{\"ok\":true}"))
        val authed = CountDownLatch(1)
        api.keepMovie(1) { _, _ -> authed.countDown() }
        assertTrue(authed.await(2, TimeUnit.SECONDS))
        assertEquals("Bearer synthetic-test-token", server.takeRequest(2, TimeUnit.SECONDS)!!.getHeader("Authorization"))

        val blank = ApiClient(server.url("").toString().removeSuffix("/"))
        server.enqueue(MockResponse().setResponseCode(200).setBody("{\"ok\":true}"))
        val open = CountDownLatch(1)
        blank.keepMovie(1) { _, _ -> open.countDown() }
        assertTrue(open.await(2, TimeUnit.SECONDS))
        assertNull(server.takeRequest(2, TimeUnit.SECONDS)!!.getHeader("Authorization"))
    }
}
