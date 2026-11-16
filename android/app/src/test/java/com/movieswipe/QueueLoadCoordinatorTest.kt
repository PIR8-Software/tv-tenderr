package com.movieswipe

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Regression tests for F3 (queue pagination on a shrinking eligible set) and
 * F4 (load generations, stale-response rejection and deferred dispatch of the
 * newest requested mode/search/filter state - including empty and error).
 */
class QueueLoadCoordinatorTest {

    @Test
    fun nextBatchFetchesHeadOfRemainingQueue() {
        // Decided cards leave the backend's eligible set: an offset past a
        // shrinking, reshuffled set skips undecided items (F3).
        val coordinator = QueueLoadCoordinator()
        assertEquals(0, coordinator.batchSkip())
    }

    @Test
    fun requestDispatchesImmediatelyWhenIdle() {
        val coordinator = QueueLoadCoordinator()
        var dispatched = 0
        val token = coordinator.request { dispatched++ }
        assertTrue(token != null)
        assertEquals(1, dispatched)
        assertTrue(coordinator.settle(token!!))
    }

    @Test
    fun staleResponseIsRejectedAndNotRendered() {
        val coordinator = QueueLoadCoordinator()
        val stale = coordinator.request { }!!
        coordinator.request { } // newer desired state supersedes
        assertFalse(coordinator.settle(stale))
    }

    @Test
    fun deferredRequestIsDispatchedWhenInFlightSettles() {
        val coordinator = QueueLoadCoordinator()
        val first = coordinator.request { }!!
        var secondDispatched = false
        assertNull(coordinator.request { secondDispatched = true })
        assertFalse(secondDispatched)
        coordinator.settle(first)
        assertTrue(secondDispatched)
    }

    @Test
    fun settleAfterErrorResponseStillDispatchesNewestRequest() {
        // The reviewed bug: switching mode while a load was in flight was
        // silently dropped, and an old request's error/empty path never
        // dispatched the requested load, leaving the screen blank (F4).
        val coordinator = QueueLoadCoordinator()
        val first = coordinator.request { }!!
        var secondDispatched = false
        coordinator.request { secondDispatched = true }
        // First request failed or came back empty: settle() is result-agnostic.
        coordinator.settle(first)
        assertTrue(secondDispatched)
    }

    @Test
    fun onlyNewestOfMultipleDeferredRequestsIsDispatched() {
        val coordinator = QueueLoadCoordinator()
        val first = coordinator.request { }!!
        var dispatches = 0
        coordinator.request { dispatches++ } // superseded
        coordinator.request { dispatches++ } // newest wins
        coordinator.settle(first)
        assertEquals(1, dispatches)
    }

    @Test
    fun queueReloadWaitsForInFlightDecisionWrites() {
        // A reload racing an unconfirmed decision write can re-show the card
        // just decided (F3 in-flight race).
        val coordinator = QueueLoadCoordinator()
        coordinator.beginDecision()
        var dispatched = false
        assertNull(coordinator.request { dispatched = true })
        assertFalse(dispatched)
        coordinator.endDecision()
        assertTrue(dispatched)
    }

    @Test
    fun settleTwiceDoesNotDispatchTwice() {
        val coordinator = QueueLoadCoordinator()
        val token = coordinator.request { }!!
        coordinator.settle(token)
        var dispatches = 0
        coordinator.request { dispatches++ }
        coordinator.settle(token) // stale duplicate settle
        assertEquals(1, dispatches)
    }

    @Test
    fun isCurrentTracksLatestGeneration() {
        val coordinator = QueueLoadCoordinator()
        val first = coordinator.request { }!!
        assertTrue(coordinator.isCurrent(first))
        coordinator.settle(first)
        val second = coordinator.request { }!!
        assertFalse(coordinator.isCurrent(first))
        assertTrue(coordinator.isCurrent(second))
    }
}
