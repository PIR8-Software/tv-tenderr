package com.movieswipe

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

/**
 * Regression tests for F6: malformed "successful" API responses must produce
 * exactly one normal error callback - never an uncaught exception on the
 * OkHttp callback thread, never a silently swallowed response, and never a
 * success callback carrying null/broken models. Covers malformed JSON, HTML,
 * JSON null, empty body, `{}` and missing collection fields with MockWebServer.
 */
class ApiClientMalformedResponseTest {
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

    private fun expectSingleErrorCallback(
        body: String,
        invoke: (((MoviesResponse?, String?) -> Unit) -> Unit),
    ) {
        server.enqueue(MockResponse().setResponseCode(200).setBody(body))
        val latch = CountDownLatch(1)
        val callbacks = AtomicInteger(0)
        var result: MoviesResponse? = null
        var error: String? = "unset"
        invoke { movies, failure ->
            callbacks.incrementAndGet()
            result = movies
            error = failure
            latch.countDown()
        }
        assertTrue(
            "callback was never invoked for body: $body",
            latch.await(2, TimeUnit.SECONDS),
        )
        Thread.sleep(200) // allow any stray second callback to surface
        assertEquals("exactly one callback for body: $body", 1, callbacks.get())
        assertNull("expected no model for body: $body", result)
        assertNotNull("expected error for body: $body", error)
    }

    @Test
    fun htmlBodyProducesSingleErrorCallback() {
        expectSingleErrorCallback("<html><body>login</body></html>") {
            api.getMovies(callback = it)
        }
    }

    @Test
    fun malformedJsonProducesSingleErrorCallback() {
        expectSingleErrorCallback("{\"movies\": [") { api.getMovies(callback = it) }
    }

    @Test
    fun jsonNullLiteralProducesSingleErrorCallback() {
        expectSingleErrorCallback("null") { api.getMovies(callback = it) }
    }

    @Test
    fun emptyBodyProducesSingleErrorCallback() {
        expectSingleErrorCallback("") { api.getMovies(callback = it) }
    }

    @Test
    fun emptyJsonObjectProducesSingleErrorCallback() {
        expectSingleErrorCallback("{}") { api.getMovies(callback = it) }
    }

    @Test
    fun missingCollectionFieldProducesSingleErrorCallback() {
        expectSingleErrorCallback("{\"total\": 5}") { api.getMovies(callback = it) }
    }

    @Test
    fun itemMissingRequiredFieldProducesSingleErrorCallback() {
        expectSingleErrorCallback("{\"movies\": [{\"id\": 1}], \"total\": 1}") {
            api.getMovies(callback = it)
        }
    }

    @Test
    fun validResponseSucceedsExactlyOnce() {
        server.enqueue(
            MockResponse().setResponseCode(200)
                .setBody("{\"movies\": [{\"id\": 1, \"title\": \"A\"}], \"total\": 1}"),
        )
        val latch = CountDownLatch(1)
        val callbacks = AtomicInteger(0)
        var result: MoviesResponse? = null
        var error: String? = "unset"
        api.getMovies(callback = { movies, failure ->
            callbacks.incrementAndGet()
            result = movies
            error = failure
            latch.countDown()
        })
        assertTrue(latch.await(2, TimeUnit.SECONDS))
        Thread.sleep(200)
        assertEquals(1, callbacks.get())
        assertNull(error)
        assertNotNull(result)
        assertEquals(1, result!!.movies.size)
    }

    @Test
    fun malformedHistoryResponseProducesSingleErrorCallback() {
        server.enqueue(MockResponse().setResponseCode(200).setBody("{}"))
        val latch = CountDownLatch(1)
        val callbacks = AtomicInteger(0)
        var error: String? = "unset"
        api.getHistory { history, failure ->
            callbacks.incrementAndGet()
            error = failure
            latch.countDown()
        }
        assertTrue(latch.await(2, TimeUnit.SECONDS))
        Thread.sleep(200)
        assertEquals(1, callbacks.get())
        assertNotNull(error)
    }

    @Test
    fun showsMissingCollectionProducesSingleErrorCallback() {
        server.enqueue(MockResponse().setResponseCode(200).setBody("{\"total\": 3}"))
        val latch = CountDownLatch(1)
        val callbacks = AtomicInteger(0)
        var result: ShowsResponse? = null
        var error: String? = "unset"
        api.getShows(callback = { shows, failure ->
            callbacks.incrementAndGet()
            result = shows
            error = failure
            latch.countDown()
        })
        assertTrue(latch.await(2, TimeUnit.SECONDS))
        Thread.sleep(200)
        assertEquals(1, callbacks.get())
        assertNull(result)
        assertNotNull(error)
    }
}
