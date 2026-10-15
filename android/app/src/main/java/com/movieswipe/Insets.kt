package com.movieswipe

import android.app.Activity
import android.view.ViewGroup
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat

/**
 * Applies system-bar insets to the activity content so nothing renders under
 * the status or navigation bars. Edge-to-edge is enforced for apps targeting
 * SDK 35+, and the opt-out disappears at SDK 36, so insets are handled
 * explicitly instead.
 */
fun Activity.applySystemBarInsets() {
    WindowCompat.setDecorFitsSystemWindows(window, false)
    val content = findViewById<ViewGroup>(android.R.id.content)
    ViewCompat.setOnApplyWindowInsetsListener(content) { view, insets ->
        val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
        view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
        insets
    }
}
