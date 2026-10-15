package com.movieswipe

import org.junit.Assert.assertEquals
import org.junit.Test

class AdaptiveLayoutTest {
    @Test
    fun compactScreensUseOneColumn() {
        assertEquals(1, gridSpanCount(320))
        assertEquals(1, gridSpanCount(599))
    }

    @Test
    fun mediumScreensUseTwoColumns() {
        assertEquals(2, gridSpanCount(600))
        assertEquals(2, gridSpanCount(839))
    }

    @Test
    fun expandedScreensUseThreeColumns() {
        assertEquals(3, gridSpanCount(840))
        assertEquals(3, gridSpanCount(1280))
    }
}
