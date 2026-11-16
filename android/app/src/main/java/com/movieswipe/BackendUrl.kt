package com.movieswipe

/**
 * Validation and safe resolution of the configured backend base URL (F5).
 *
 * Only absolute HTTP(S) URLs with a host are accepted. An invalid candidate
 * is rejected before any persistence or request construction, and callers
 * resolve stored configuration to a safe fallback instead of crashing.
 */
object BackendUrl {
    const val DEFAULT = "http://localhost:8899"

    /**
     * Returns a normalized base URL (trimmed, without trailing slash) when
     * [raw] is a usable absolute HTTP(S) URL with a host; null otherwise.
     */
    fun normalize(raw: String?): String? {
        val trimmed = raw?.trim().orEmpty()
        if (trimmed.isEmpty()) return null
        val uri = try {
            java.net.URI(trimmed)
        } catch (e: Exception) {
            return null
        }
        val scheme = uri.scheme?.lowercase()
        if (scheme != "http" && scheme != "https") return null
        val host = uri.host ?: return null
        if (host.isEmpty()) return null
        return trimmed.trimEnd('/')
    }

    /**
     * Resolve a stored setting to a normalized URL, falling back to
     * [fallback] when the stored value is missing or invalid. Never throws.
     */
    fun resolve(stored: String?, fallback: String = DEFAULT): String =
        normalize(stored) ?: normalize(fallback) ?: DEFAULT
}
