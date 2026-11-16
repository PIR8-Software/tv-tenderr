package com.movieswipe

/**
 * Coordinates queue batch loading for the review screen (F3/F4).
 *
 * - Every confirmed card decision leaves the backend's eligible set, so the
 *   next batch is always fetched from the HEAD of the remaining queue: an
 *   offset into a shrinking, reshuffled set skips undecided items.
 * - Every load request carries a generation. Responses from superseded
 *   requests are ignored, and a request made while a load is in flight is
 *   dispatched as soon as the in-flight response settles - on success, empty
 *   AND error paths - so the newest requested mode/search/filter state is
 *   never silently discarded.
 * - A queue reload is deferred while decision writes are still in flight so a
 *   just-decided card cannot reappear in the next fetch.
 */
class QueueLoadCoordinator {
    companion object {
        const val BATCH_LIMIT = 20
    }

    private var generation = 0
    private var inFlight = false
    private var pendingDecisions = 0
    private var pendingDispatch: ((Int) -> Unit)? = null

    /**
     * Request a load of the latest desired queue state. Returns the
     * generation token when the request was dispatched now, or null when it
     * was deferred (a load or decision write is still in flight); the newest
     * deferred request is dispatched when the blocker settles.
     */
    fun request(dispatch: (Int) -> Unit): Int? {
        generation++
        pendingDispatch = dispatch
        return flush()
    }

    /**
     * Report that the response for [token] settled (success, empty or error).
     * Returns true when the response is current and may be rendered; stale
     * responses return false and are never rendered. Always flushes a
     * deferred request afterwards.
     */
    fun settle(token: Int): Boolean {
        val current = token == generation
        inFlight = false
        flush()
        return current
    }

    /** True when [token] belongs to the newest requested load. */
    fun isCurrent(token: Int): Boolean = token == generation

    /** Announce a decision write; queue reloads wait until it settles. */
    fun beginDecision() {
        pendingDecisions++
    }

    /** Report a settled decision write (success or failure). */
    fun endDecision() {
        pendingDecisions = maxOf(0, pendingDecisions - 1)
        flush()
    }

    /**
     * Offset for the next queue fetch. Decided cards have left the eligible
     * set, so the next batch is always the head of the remaining queue.
     */
    fun batchSkip(): Int = 0

    private fun flush(): Int? {
        if (inFlight || pendingDecisions > 0) return null
        val dispatch = pendingDispatch ?: return null
        pendingDispatch = null
        inFlight = true
        dispatch(generation)
        return generation
    }
}
