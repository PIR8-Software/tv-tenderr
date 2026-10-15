package com.movieswipe

/**
 * Column count for list grids by available width, following the Material
 * window size class breakpoints (compact < 600dp, medium < 840dp, expanded).
 */
fun gridSpanCount(screenWidthDp: Int): Int = when {
    screenWidthDp >= 840 -> 3
    screenWidthDp >= 600 -> 2
    else -> 1
}
