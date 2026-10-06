package com.movieswipe

import android.animation.Animator
import android.animation.AnimatorListenerAdapter
import android.animation.AnimatorSet
import android.animation.ObjectAnimator
import android.graphics.Color
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.view.animation.AccelerateDecelerateInterpolator
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.cardview.widget.CardView
import androidx.core.view.updateLayoutParams
import com.bumptech.glide.Glide
import com.movieswipe.databinding.ActivityMainBinding
import kotlin.math.abs

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var api: ApiClient
    private val movies = mutableListOf<Movie>()
    private val shows = mutableListOf<Show>()
    private val discoverItems = mutableListOf<DiscoverItem>()
    private var currentIndex = 0
    private var isLoading = false
    private var mode = "movies" // "movies", "shows", "discover"
    private var discoverType = "movies" // "movies" or "shows" within discover
    private var currentSearchQuery = ""
    private var currentGenre = ""
    private var currentMinYear = 0
    private var currentMaxYear = 0
    private var currentMinRating = 0f
    private var selectedProviders = ""
    private var discoverPage = 1
    private var discoverSort = "popularity.desc"
    private var discoverRequestId = 0  // Track which request is current

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val prefs = getSharedPreferences("movieswipe", MODE_PRIVATE)
        val serverUrl = prefs.getString("server_url", "http://localhost:8899") ?: "http://localhost:8899"
        api = ApiClient(serverUrl, storedApiToken(this))

        // Show splash screen
        setContentView(R.layout.activity_splash)

        // After delay, load main UI
        window.decorView.postDelayed({
            binding = ActivityMainBinding.inflate(layoutInflater)
            setContentView(binding.root)
            setupButtons()
            setupNavigation()
            updateActionAccessibility()
            loadMovies()
            checkForUpdates()
        }, 2000)
    }

    override fun onResume() {
        super.onResume()
        if (!::api.isInitialized) return
        val prefs = getSharedPreferences("movieswipe", MODE_PRIVATE)
        api.setUrl(prefs.getString("server_url", "http://localhost:8899") ?: "http://localhost:8899")
        api.setToken(storedApiToken(this))
        if (::binding.isInitialized) reloadCurrentQueue()
    }

    override fun onStop() {
        super.onStop()
        // Leaving the screen cancels an uncommitted destructive action.
        undoRunnable?.let { undoHandler?.removeCallbacks(it) }
        pendingBlock = null
        if (::binding.isInitialized) findViewById<View>(R.id.undoBanner).visibility = View.GONE
    }

    private fun reloadCurrentQueue() {
        currentIndex = 0
        when (mode) {
            "movies" -> loadMovies()
            "shows" -> loadShows()
            else -> { discoverPage = 1; loadDiscover() }
        }
    }

    private fun checkForUpdates() {
        val currentVersion = try {
            packageManager.getPackageInfo(packageName, 0).versionName ?: "1.0"
        } catch (e: Exception) { "1.0" }

        api.checkForUpdates { info, _ ->
            if (info != null) {
                val latestVersion = info.version ?: "0"
                val latestParts = latestVersion.split(".").map { it.toIntOrNull() ?: 0 }
                val currentParts = currentVersion.split(".").map { it.toIntOrNull() ?: 0 }
                val maxLen = maxOf(latestParts.size, currentParts.size)
                var isNewer = false
                for (i in 0 until maxLen) {
                    val l = latestParts.getOrElse(i) { 0 }
                    val c = currentParts.getOrElse(i) { 0 }
                    if (l > c) { isNewer = true; break }
                    if (l < c) break
                }
                if (isNewer) {
                    runOnUiThread {
                        android.widget.Toast.makeText(
                            this,
                            "⬆ Update available: v${info.version}",
                            android.widget.Toast.LENGTH_LONG
                        ).show()
                    }
                }
            }
        }
    }

    private fun setupNavigation() {
        binding.btnHistory.setOnClickListener {
            val intent = android.content.Intent(this, HistoryActivity::class.java)
            intent.putExtra("mode", mode)
            startActivity(intent)
        }

        binding.btnRefresh.setOnClickListener {
            api.refreshPlex { ok, _ ->
                runOnUiThread {
                    if (ok) {
                        android.widget.Toast.makeText(this, "🔄 Plex library refreshed", android.widget.Toast.LENGTH_SHORT).show()
                    } else {
                        android.widget.Toast.makeText(this, "❌ Refresh failed", android.widget.Toast.LENGTH_SHORT).show()
                    }
                }
            }
        }

        binding.btnSettings.setOnClickListener {
            startActivity(android.content.Intent(this, SettingsActivity::class.java))
        }

        binding.btnCalendar.setOnClickListener {
            startActivity(android.content.Intent(this, CalendarActivity::class.java))
        }

        // Show search bar for movies/shows, hide for discover
        binding.searchBar.visibility = View.VISIBLE  // Visible for movies/shows

        // Search functionality
        binding.etSearch.setOnEditorActionListener { textView, actionId, _ ->
            if (actionId == android.view.inputmethod.EditorInfo.IME_ACTION_SEARCH) {
                val query = textView.text.toString().trim()
                currentSearchQuery = query
                currentIndex = 0
                movies.clear()
                shows.clear()
                binding.cardContainer.removeAllViews()
                when (mode) {
                    "movies" -> loadMovies()
                    "shows" -> loadShows()
                }
                true
            } else false
        }

        // Filter button
        binding.btnFilter.setOnClickListener {
            showFilterDialog()
        }

        // Stats button
        binding.btnStats.setOnClickListener {
            showStatsDialog()
        }

        binding.tvMode.setOnClickListener {
            mode = when (mode) {
                "movies" -> "shows"
                "shows" -> "discover"
                else -> "movies"
            }
            binding.tvMode.text = when (mode) {
                "movies" -> "Movies"
                "shows" -> "Shows"
                "discover" -> "Discover"
                else -> "Movies"
            }
            updateActionAccessibility()
            binding.tvMode.setTextColor(when (mode) {
                "discover" -> resources.getColor(android.R.color.holo_orange_light, theme)
                else -> resources.getColor(android.R.color.holo_green_light, theme)
            })
            binding.tvStats.visibility = if (mode == "discover") View.INVISIBLE else View.VISIBLE
                        // Reset discover type when entering discover mode
            if (mode == "discover") {
                discoverType = "movies"
            }
            currentIndex = 0
            discoverPage = 1
            currentSearchQuery = ""
            binding.etSearch.text.clear()
            movies.clear()
            shows.clear()
            discoverItems.clear()
            binding.cardContainer.removeAllViews()
            binding.searchBar.visibility = if (mode == "discover") View.GONE else View.VISIBLE
            when (mode) {
                "movies" -> loadMovies()
                "shows" -> loadShows()
                "discover" -> loadDiscover()
            }
        }



    }

    private fun showStatsDialog() {
        api.getStats { stats, error ->
            runOnUiThread {
                if (stats != null) {
                    val dialogView = layoutInflater.inflate(R.layout.dialog_stats, null)
                    val statsMovies = dialogView.findViewById<LinearLayout>(R.id.statsMovies)
                    val statsShows = dialogView.findViewById<LinearLayout>(R.id.statsShows)
                    val statsDiscover = dialogView.findViewById<LinearLayout>(R.id.statsDiscover)
                    val btnClose = dialogView.findViewById<TextView>(R.id.btnCloseStats)

                    fun addStatRow(container: LinearLayout, label: String, value: Int, color: String = "#ffffff") {
                        val row = LinearLayout(this)
                        row.orientation = LinearLayout.HORIZONTAL
                        row.setPadding(0, 4, 0, 4)
                        val tvLabel = TextView(this)
                        tvLabel.text = label
                        tvLabel.setTextColor(android.graphics.Color.parseColor("#aaaaaa"))
                        tvLabel.textSize = 14f
                        tvLabel.layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
                        val tvValue = TextView(this)
                        tvValue.text = value.toString()
                        tvValue.setTextColor(android.graphics.Color.parseColor(color))
                        tvValue.textSize = 14f
                        tvValue.typeface = android.graphics.Typeface.DEFAULT_BOLD
                        row.addView(tvLabel)
                        row.addView(tvValue)
                        container.addView(row)
                    }

                    // Movies
                    addStatRow(statsMovies, "Total", stats.movies.total)
                    addStatRow(statsMovies, "Kept", stats.movies.kept, "#2ecc71")
                    addStatRow(statsMovies, "Super Kept", stats.movies.superKept, "#f1c40f")
                    addStatRow(statsMovies, "Blocked", stats.movies.blocked, "#e74c3c")
                    addStatRow(statsMovies, "Skipped", stats.movies.skipped, "#aaaaaa")
                    addStatRow(statsMovies, "Undecided", stats.movies.undecided, "#555555")

                    // Shows
                    addStatRow(statsShows, "Total", stats.shows.total)
                    addStatRow(statsShows, "Kept", stats.shows.kept, "#2ecc71")
                    addStatRow(statsShows, "Super Kept", stats.shows.superKept, "#f1c40f")
                    addStatRow(statsShows, "Blocked", stats.shows.blocked, "#e74c3c")
                    addStatRow(statsShows, "Skipped", stats.shows.skipped, "#aaaaaa")
                    addStatRow(statsShows, "Undecided", stats.shows.undecided, "#555555")

                    // Discover
                    addStatRow(statsDiscover, "Added", stats.discover.added, "#2ecc71")
                    addStatRow(statsDiscover, "Hidden", stats.discover.hidden, "#e74c3c")

                    val dialog = android.app.AlertDialog.Builder(this)
                        .setView(dialogView)
                        .show()
                    dialog.window?.setLayout(
                        (resources.displayMetrics.widthPixels * 0.92).toInt(),
                        android.view.ViewGroup.LayoutParams.WRAP_CONTENT
                    )
                    dialog.window?.decorView?.setBackgroundColor(android.graphics.Color.TRANSPARENT)

                    btnClose.setOnClickListener { dialog.dismiss() }
                } else {
                    android.widget.Toast.makeText(this, "Failed to load stats: $error", android.widget.Toast.LENGTH_SHORT).show()
                }
            }
        }
    }

    private fun showFilterDialog() {
        val dialogView = layoutInflater.inflate(R.layout.dialog_filter, null)
        val spinnerGenre = dialogView.findViewById<android.widget.Spinner>(R.id.spinnerGenre)
        val spinnerRating = dialogView.findViewById<android.widget.Spinner>(R.id.spinnerRating)
        val etMinYear = dialogView.findViewById<EditText>(R.id.etMinYear)
        val etMaxYear = dialogView.findViewById<EditText>(R.id.etMaxYear)
        val btnApply = dialogView.findViewById<TextView>(R.id.btnApplyFilters)
        val btnClear = dialogView.findViewById<TextView>(R.id.btnClearFilters)

        // Genre dropdown
        val genres = listOf("Any Genre", "Action", "Adventure", "Animation", "Comedy", "Crime",
            "Documentary", "Drama", "Family", "Fantasy", "History", "Horror",
            "Music", "Mystery", "Romance", "Sci-Fi", "Thriller", "War", "Western")
        val genreAdapter = android.widget.ArrayAdapter(this, R.layout.spinner_item, genres)
        genreAdapter.setDropDownViewResource(R.layout.spinner_item)
        spinnerGenre.adapter = genreAdapter
        val genreIdx = genres.indexOfFirst { it.equals(currentGenre, ignoreCase = true) }
        if (genreIdx > 0) spinnerGenre.setSelection(genreIdx)

        // Rating dropdown
        val ratings = listOf("Any Rating", "5+", "6+", "7+", "8+", "9+")
        val ratingValues = listOf(0f, 5f, 6f, 7f, 8f, 9f)
        val ratingAdapter = android.widget.ArrayAdapter(this, R.layout.spinner_item, ratings)
        ratingAdapter.setDropDownViewResource(R.layout.spinner_item)
        spinnerRating.adapter = ratingAdapter
        val ratingIdx = ratingValues.indexOf(currentMinRating)
        if (ratingIdx >= 0) spinnerRating.setSelection(ratingIdx)

        // Pre-fill year values
        if (currentMinYear > 0) etMinYear.setText(currentMinYear.toString())
        if (currentMaxYear > 0) etMaxYear.setText(currentMaxYear.toString())

        val dialog = android.app.AlertDialog.Builder(this)
            .setView(dialogView)
            .show()

        dialog.window?.setLayout(
            (resources.displayMetrics.widthPixels * 0.92).toInt(),
            android.view.ViewGroup.LayoutParams.WRAP_CONTENT
        )
        dialog.window?.decorView?.setBackgroundColor(android.graphics.Color.TRANSPARENT)

        btnApply.setOnClickListener {
            val selGenre = spinnerGenre.selectedItemPosition
            currentGenre = if (selGenre == 0) "" else genres[selGenre]
            val selRating = spinnerRating.selectedItemPosition
            currentMinRating = ratingValues[selRating]
            currentMinYear = etMinYear.text.toString().toIntOrNull() ?: 0
            currentMaxYear = etMaxYear.text.toString().toIntOrNull() ?: 0
            applyFilters()
            dialog.dismiss()
        }

        btnClear.setOnClickListener {
            currentGenre = ""
            currentMinYear = 0
            currentMaxYear = 0
            currentMinRating = 0f
            currentSearchQuery = ""
            binding.etSearch.text.clear()
            applyFilters()
            dialog.dismiss()
        }
    }

    private fun applyFilters() {
        currentIndex = 0
        movies.clear()
        shows.clear()
        binding.cardContainer.removeAllViews()
        when (mode) {
            "movies" -> loadMovies()
            "shows" -> loadShows()
        }
        val activeFilters = mutableListOf<String>()
        if (currentGenre.isNotBlank()) activeFilters.add(currentGenre)
        if (currentMinYear > 0) activeFilters.add("≥$currentMinYear")
        if (currentMaxYear > 0) activeFilters.add("≤$currentMaxYear")
        if (currentMinRating > 0f) activeFilters.add("⭐≥$currentMinRating")
        if (currentSearchQuery.isNotBlank()) activeFilters.add("[" + currentSearchQuery + "]")
        binding.btnFilter.text = if (activeFilters.isEmpty()) "⚙ Filter" else "⚙ ${activeFilters.joinToString(" ")}"
    }

    private fun updateActionAccessibility() {
        binding.tvMode.contentDescription = "Change mode, current ${binding.tvMode.text}"
        binding.btnKeep.contentDescription = if (mode == "discover") "Add to library" else "Keep; long press to Super Keep"
        binding.btnSkip.contentDescription = if (mode == "shows") "Skip; long press to Clean files" else "Skip for now"
        binding.btnBlock.contentDescription = if (mode == "discover") "Dislike; Undo available for 10 seconds" else "Block and delete; Undo available for 10 seconds"
    }

    private fun setupButtons() {
        binding.btnKeep.setOnClickListener {
            when (mode) {
                "movies" -> {
                    if (movies.isNotEmpty() && currentIndex < movies.size) {
                        val movie = movies[currentIndex]
                        animateCardOut(true) { api.keepMovie(movie.id) { ok, error -> reportActionFailure(ok, error) }; advanceCard() }
                    }
                }
                "shows" -> {
                    if (shows.isNotEmpty() && currentIndex < shows.size) {
                        val show = shows[currentIndex]
                        animateCardOut(true) { api.keepShow(show.id) { ok, error -> reportActionFailure(ok, error) }; advanceCard() }
                    }
                }
                "discover" -> {
                    if (discoverItems.isNotEmpty() && currentIndex < discoverItems.size) {
                        val item = discoverItems[currentIndex]
                        animateCardOut(true) {
                            if (discoverType == "movies") api.addMovieFromDiscover(item.tmdbId) { ok, error -> reportActionFailure(ok, error) }
                            else api.addShowFromDiscover(item.tmdbId) { ok, error -> reportActionFailure(ok, error) }
                            advanceCard()
                        }
                    }
                }
            }
        }

        // Long press keep = super keep (only for library modes)
        binding.btnKeep.setOnLongClickListener {
            when (mode) {
                "movies" -> {
                    if (movies.isNotEmpty() && currentIndex < movies.size) {
                        val movie = movies[currentIndex]
                        animateCardOut(true) { api.superKeepMovie(movie.id) { ok, error -> reportActionFailure(ok, error) }; advanceCard() }
                        android.widget.Toast.makeText(this, "⭐ Super Keep: ${movie.title}", android.widget.Toast.LENGTH_SHORT).show()
                    }
                }
                "shows" -> {
                    if (shows.isNotEmpty() && currentIndex < shows.size) {
                        val show = shows[currentIndex]
                        animateCardOut(true) { api.superKeepShow(show.id) { ok, error -> reportActionFailure(ok, error) }; advanceCard() }
                        android.widget.Toast.makeText(this, "⭐ Super Keep: ${show.title}", android.widget.Toast.LENGTH_SHORT).show()
                    }
                }
                "discover" -> {
                    // In discover, long-press keep = add and search immediately
                    if (discoverItems.isNotEmpty() && currentIndex < discoverItems.size) {
                        val item = discoverItems[currentIndex]
                        animateCardOut(true) {
                            if (discoverType == "movies") api.addMovieFromDiscover(item.tmdbId) { ok, error -> reportActionFailure(ok, error) }
                            else api.addShowFromDiscover(item.tmdbId) { ok, error -> reportActionFailure(ok, error) }
                            advanceCard()
                        }
                        android.widget.Toast.makeText(this, "⬇️ Added: ${item.title}", android.widget.Toast.LENGTH_SHORT).show()
                    }
                }
            }
            true
        }

        binding.btnBlock.setOnClickListener {
            when (mode) {
                "movies" -> { if (movies.isNotEmpty() && currentIndex < movies.size) blockWithUndo() }
                "shows" -> { if (shows.isNotEmpty() && currentIndex < shows.size) blockShowWithUndo() }
                "discover" -> {
                    if (discoverItems.isNotEmpty() && currentIndex < discoverItems.size) {
                        dislikeDiscoverWithUndo()
                    }
                }
            }
        }

        binding.btnSkip.setOnClickListener {
            when (mode) {
                "movies" -> {
                    if (movies.isNotEmpty() && currentIndex < movies.size) {
                        val movie = movies[currentIndex]
                        api.skipMovie(movie.id) { ok, error -> reportActionFailure(ok, error) }; advanceCard()
                    }
                }
                "shows" -> {
                    if (shows.isNotEmpty() && currentIndex < shows.size) {
                        val show = shows[currentIndex]
                        api.skipShow(show.id) { ok, error -> reportActionFailure(ok, error) }; advanceCard()
                    }
                }
                "discover" -> {
                    if (discoverItems.isNotEmpty() && currentIndex < discoverItems.size) {
                        val item = discoverItems[currentIndex]
                        api.hideDiscover(item.tmdbId, item.title, item.year, item.posterUrl, discoverType) { ok, error -> reportActionFailure(ok, error) }; advanceCard()
                    }
                }
            }
        }

        // Long press skip on shows = clean files
        binding.btnSkip.setOnLongClickListener {
            if (mode == "shows" && shows.isNotEmpty() && currentIndex < shows.size) {
                val show = shows[currentIndex]
                val showIndex = currentIndex
                animateCardOut(false) {
                    showUndoBanner("\"${show.title}\" files will be removed") {
                        currentIndex = showIndex
                        showCurrentCard()
                    }
                    pendingBlock = {
                        api.cleanShow(show.id) { ok, error ->
                            reportActionFailure(ok, error)
                            if (ok) runOnUiThread { android.widget.Toast.makeText(this, "🧹 Cleaned: ${show.title}", android.widget.Toast.LENGTH_SHORT).show() }
                        }
                    }
                    advanceCard()
                }
            }
            true
        }
    }

    private fun blockWithUndo() {
        val movie = movies[currentIndex]
        val movieIndex = currentIndex
        animateCardOut(false) {
            showUndoBanner("\"${movie.title}\" will be deleted") {
                currentIndex = movieIndex
                showCurrentCard()
            }
            pendingBlock = { api.blockMovie(movie.id) { ok, error -> reportActionFailure(ok, error) } }
            advanceCard()
        }
    }

    private fun blockShowWithUndo() {
        val show = shows[currentIndex]
        val showIndex = currentIndex
        animateCardOut(false) {
            showUndoBanner("\"${show.title}\" will be deleted") {
                currentIndex = showIndex
                showCurrentCard()
            }
            pendingBlock = { api.blockShow(show.id) { ok, error -> reportActionFailure(ok, error) } }
            advanceCard()
        }
    }

    private fun dislikeDiscoverWithUndo() {
        val item = discoverItems[currentIndex]
        val itemIndex = currentIndex
        val itemType = discoverType
        animateCardOut(false) {
            showUndoBanner("\"${item.title}\" will be added to Import List Exclusions") {
                currentIndex = itemIndex
                showCurrentCard()
            }
            pendingBlock = {
                api.dislikeDiscover(item.tmdbId, item.title, item.year, item.posterUrl, itemType) { ok, error -> reportActionFailure(ok, error) }
            }
            advanceCard()
        }
    }

    private var undoHandler: android.os.Handler? = null
    private var undoRunnable: Runnable? = null
    private var pendingBlock: (() -> Unit)? = null

    private fun reportActionFailure(ok: Boolean, error: String?) {
        if (ok) return
        runOnUiThread {
            Toast.makeText(this, error ?: "Action failed", Toast.LENGTH_LONG).show()
            reloadCurrentQueue()
        }
    }

    private fun showUndoBanner(message: String, onUndo: () -> Unit) {
        val banner = findViewById<LinearLayout>(R.id.undoBanner)
        val tvMessage = findViewById<TextView>(R.id.tvUndoMessage)
        val btnUndo = findViewById<Button>(R.id.btnUndoAction)

        // Cancel any existing timer and pending block
        undoRunnable?.let { undoHandler?.removeCallbacks(it) }
        pendingBlock = null

        tvMessage.text = message
        btnUndo.setOnClickListener {
            onUndo()
            banner.visibility = View.GONE
            undoRunnable?.let { undoHandler?.removeCallbacks(it) }
            pendingBlock = null
        }
        banner.visibility = View.VISIBLE

        // After 10 seconds, execute the destructive action and hide the banner.
        undoHandler = android.os.Handler(mainLooper)
        undoRunnable = Runnable {
            banner.visibility = View.GONE
            pendingBlock?.invoke()
            pendingBlock = null
        }
        undoHandler?.postDelayed(undoRunnable!!, 10000)
    }

    private fun loadMovies() {
        if (isLoading) return
        isLoading = true
        binding.tvStats.text = ""

        api.getMovies(skip = currentIndex, limit = 20, genre = currentGenre, minYear = currentMinYear, maxYear = currentMaxYear, minRating = currentMinRating, search = currentSearchQuery) { response, error ->
            runOnUiThread {
                isLoading = false
                if (error != null) {
                    binding.tvStats.text = "ERROR"
                    return@runOnUiThread
                }
                if (response != null && response.movies.isNotEmpty()) {
                    movies.clear()
                    movies.addAll(response.movies)
                    currentIndex = 0
                    binding.tvStats.text = "${response.total} movies"
                    showCurrentCard()
                } else {
                    binding.tvStats.text = "No movies to review!"
                }
            }
        }
    }

    private fun loadShows() {
        if (isLoading) return
        isLoading = true
        binding.tvStats.text = ""

        api.getShows(skip = currentIndex, limit = 20, genre = currentGenre, minYear = currentMinYear, maxYear = currentMaxYear, minRating = currentMinRating, search = currentSearchQuery) { response, error ->
            runOnUiThread {
                isLoading = false
                if (error != null) {
                    binding.tvStats.text = "ERROR"
                    return@runOnUiThread
                }
                if (response != null && response.shows.isNotEmpty()) {
                    shows.clear()
                    shows.addAll(response.shows)
                    currentIndex = 0
                    binding.tvStats.text = "${response.total} shows"
                    showCurrentCard()
                } else {
                    binding.tvStats.text = "No shows to review!"
                }
            }
        }
    }

    private fun showCurrentCard() {
        binding.cardContainer.removeAllViews()

        when (mode) {
            "movies" -> {
                if (currentIndex >= movies.size) { loadMovies(); return }
                val movie = movies[currentIndex]
                val cardView = createMovieCardView(movie)
                binding.cardContainer.addView(cardView)
                setupMovieSwipeGesture(cardView, movie)
            }
            "shows" -> {
                if (currentIndex >= shows.size) { loadShows(); return }
                val show = shows[currentIndex]
                val cardView = createShowCardView(show)
                binding.cardContainer.addView(cardView)
                setupShowSwipeGesture(cardView, show)
            }
            "discover" -> {
                if (currentIndex >= discoverItems.size) {
                    discoverPage++
                    loadDiscover()
                    return
                }
                val item = discoverItems[currentIndex]
                val cardView = createDiscoverCardView(item)
                binding.cardContainer.addView(cardView)
                setupDiscoverSwipeGesture(cardView, item)
            }
        }
    }

    private fun createMovieCardView(movie: Movie): CardView {
        val cardView = LayoutInflater.from(this).inflate(R.layout.card_movie, binding.cardContainer, false) as CardView

        // Hide discover controls on movie cards
        cardView.findViewById<LinearLayout>(R.id.discoverControls)?.visibility = View.GONE

        val ivPoster = cardView.findViewById<ImageView>(R.id.ivPoster)
        val tvTitle = cardView.findViewById<TextView>(R.id.tvTitle)
        val tvYear = cardView.findViewById<TextView>(R.id.tvYear)
        val tvSize = cardView.findViewById<TextView>(R.id.tvSize)
        val tvRating = cardView.findViewById<TextView>(R.id.tvRating)
        val tvGenres = cardView.findViewById<TextView>(R.id.tvGenres)
        val tvCast = cardView.findViewById<TextView>(R.id.tvCast)
        val tvOverview = cardView.findViewById<TextView>(R.id.tvOverview)
        val tvKeepLabel = cardView.findViewById<TextView>(R.id.tvKeepLabel)
        val tvBlockLabel = cardView.findViewById<TextView>(R.id.tvBlockLabel)

        tvTitle.text = movie.title
        tvYear.text = movie.year?.toString() ?: ""
        tvSize.text = "${movie.sizeGB} GB"
        tvRating.text = movie.rating?.let { String.format("%.1f", it) } ?: ""
        tvGenres.text = movie.genres.joinToString(" · ")
        tvCast.text = movie.cast?.joinToString(", ") ?: ""
        val tvWatchedM = cardView.findViewById<TextView>(R.id.tvWatched)
        if (movie.watched) {
            tvWatchedM.visibility = View.VISIBLE
            tvWatchedM.text = "👁 Watched"
        } else {
            tvWatchedM.visibility = View.GONE
        }
        tvOverview.text = movie.overview

        // Trailer and IMDb buttons
        val linkButtons = cardView.findViewById<LinearLayout>(R.id.linkButtons)
        val btnTrailer = cardView.findViewById<TextView>(R.id.btnTrailer)
        val btnImdb = cardView.findViewById<TextView>(R.id.btnImdb)
        linkButtons.visibility = View.VISIBLE
        btnTrailer.visibility = if (movie.trailerId != null) View.VISIBLE else View.GONE
        btnImdb.visibility = if (movie.imdbId != null) View.VISIBLE else View.GONE
        btnTrailer.setOnClickListener {
            val intent = android.content.Intent(android.content.Intent.ACTION_VIEW,
                android.net.Uri.parse("https://www.youtube.com/watch?v=${movie.trailerId}"))
            startActivity(intent)
        }
        btnImdb.setOnClickListener {
            val intent = android.content.Intent(android.content.Intent.ACTION_VIEW,
                android.net.Uri.parse("https://www.imdb.com/title/${movie.imdbId}"))
            startActivity(intent)
        }

        // Load poster
        movie.posterUrl?.let { url ->
            Glide.with(this)
                .load(url)
                .centerCrop()
                .into(ivPoster)
        }

        return cardView
    }

    private fun setupMovieSwipeGesture(cardView: CardView, movie: Movie) {
        var startX = 0f
        var startY = 0f
        var currentX = 0f
        var currentY = 0f
        val threshold = 200f

        val tvKeepLabel = cardView.findViewById<TextView>(R.id.tvKeepLabel)
        val tvBlockLabel = cardView.findViewById<TextView>(R.id.tvBlockLabel)

        cardView.setOnTouchListener { v, event ->
            when (event.action) {
                android.view.MotionEvent.ACTION_DOWN -> {
                    startX = event.rawX
                    startY = event.rawY
                    true
                }
                android.view.MotionEvent.ACTION_MOVE -> {
                    currentX = event.rawX - startX
                    currentY = event.rawY - startY

                    if (abs(currentX) > abs(currentY) && abs(currentX) > 10) {
                        // Horizontal swipe
                        v.translationX = currentX
                        v.rotation = currentX / 30f

                        if (currentX > 50) {
                            tvKeepLabel.visibility = View.VISIBLE
                            tvKeepLabel.text = "KEEP"
                            tvKeepLabel.alpha = minOf(abs(currentX) / threshold, 1f)
                            tvKeepLabel.setTextColor(resources.getColor(android.R.color.holo_green_light, theme))
                            tvBlockLabel.visibility = View.GONE
                        } else if (currentX < -50) {
                            tvBlockLabel.visibility = View.VISIBLE
                            tvBlockLabel.alpha = minOf(abs(currentX) / threshold, 1f)
                            tvKeepLabel.visibility = View.GONE
                        }
                        true
                    } else if (currentY > 50 && abs(currentY) > abs(currentX)) {
                        // Vertical swipe down
                        v.translationY = currentY * 0.5f
                        tvKeepLabel.visibility = View.VISIBLE
                        tvKeepLabel.text = "⭐ SUPER"
                        tvKeepLabel.alpha = minOf(abs(currentY) / threshold, 1f)
                        tvKeepLabel.setTextColor(resources.getColor(android.R.color.holo_orange_light, theme))
                        tvBlockLabel.visibility = View.GONE
                        true
                    } else if (currentY < -50 && abs(currentY) > abs(currentX)) {
                        // Vertical swipe up = skip
                        v.translationY = currentY * 0.5f
                        tvBlockLabel.visibility = View.VISIBLE
                        tvBlockLabel.text = "SKIP"
                        tvBlockLabel.alpha = minOf(abs(currentY) / threshold, 1f)
                        tvBlockLabel.setTextColor(resources.getColor(android.R.color.holo_orange_light, theme))
                        tvKeepLabel.visibility = View.GONE
                        true
                    } else {
                        false
                    }
                }
                android.view.MotionEvent.ACTION_UP, android.view.MotionEvent.ACTION_CANCEL -> {
                    if (abs(currentX) > threshold && abs(currentX) > abs(currentY)) {
                        val goRight = currentX > 0
                        if (goRight) {
                            animateCardOut(true) {
                                api.keepMovie(movie.id) { ok, error -> reportActionFailure(ok, error) }
                                advanceCard()
                            }
                        } else {
                            blockWithUndo()
                        }
                    } else if (currentY > threshold && abs(currentY) > abs(currentX)) {
                        // Swipe down = super keep
                        animateCardDown {
                            api.superKeepMovie(movie.id) { ok, error -> reportActionFailure(ok, error) }
                            advanceCard()
                        }
                    } else if (currentY < -threshold && abs(currentY) > abs(currentX)) {
                        // Swipe up = skip
                        animateCardUp {
                            api.skipMovie(movie.id) { ok, error -> reportActionFailure(ok, error) }
                            advanceCard()
                        }
                    } else {
                        v.animate().translationX(0f).translationY(0f).rotation(0f).setDuration(200).start()
                        tvKeepLabel.visibility = View.GONE
                        tvBlockLabel.visibility = View.GONE
                    }
                    currentX = 0f
                    currentY = 0f
                    true
                }
                else -> false
            }
        }
    }

    private fun animateCardOut(goRight: Boolean, onEnd: () -> Unit) {
        val card = binding.cardContainer.getChildAt(0) ?: run { onEnd(); return }
        val targetX = if (goRight) card.width.toFloat() else -card.width.toFloat()

        val animX = ObjectAnimator.ofFloat(card, "translationX", targetX)
        val animR = ObjectAnimator.ofFloat(card, "rotation", if (goRight) 30f else -30f)
        val animA = ObjectAnimator.ofFloat(card, "alpha", 0f)

        AnimatorSet().apply {
            playTogether(animX, animR, animA)
            duration = 300
            interpolator = AccelerateDecelerateInterpolator()
            addListener(object : AnimatorListenerAdapter() {
                override fun onAnimationEnd(animation: Animator) {
                    onEnd()
                }
            })
            start()
        }
    }

    private fun advanceCard() {
        currentIndex++
        showCurrentCard()
    }

    private fun createShowCardView(show: Show): CardView {
        val cardView = LayoutInflater.from(this).inflate(R.layout.card_movie, binding.cardContainer, false) as CardView

        // Hide discover controls on show cards
        cardView.findViewById<LinearLayout>(R.id.discoverControls)?.visibility = View.GONE

        val ivPoster = cardView.findViewById<ImageView>(R.id.ivPoster)
        val tvTitle = cardView.findViewById<TextView>(R.id.tvTitle)
        val tvYear = cardView.findViewById<TextView>(R.id.tvYear)
        val tvSize = cardView.findViewById<TextView>(R.id.tvSize)
        val tvRating = cardView.findViewById<TextView>(R.id.tvRating)
        val tvGenres = cardView.findViewById<TextView>(R.id.tvGenres)
        val tvCast = cardView.findViewById<TextView>(R.id.tvCast)
        val tvOverview = cardView.findViewById<TextView>(R.id.tvOverview)

        tvTitle.text = show.title
        tvYear.text = show.year?.toString() ?: ""
        val statusLabel = if (show.status == "continuing") "🟢 Continuing" else "🔴 Ended"
        tvSize.text = "${show.sizeGB} GB · ${show.episodeCount} eps · $statusLabel"
        tvRating.text = show.rating?.let { String.format("%.1f", it) } ?: ""
        tvGenres.text = show.genres.joinToString(" · ")
        tvCast.text = show.cast?.joinToString(", ") ?: ""
        val tvWatchedS = cardView.findViewById<TextView>(R.id.tvWatched)
        if (show.watched) {
            tvWatchedS.visibility = View.VISIBLE
            tvWatchedS.text = "👁 Watched"
        } else {
            tvWatchedS.visibility = View.GONE
        }
        tvOverview.text = show.overview

        // IMDb button for shows
        val linkButtonsS = cardView.findViewById<LinearLayout>(R.id.linkButtons)
        val btnTrailerS = cardView.findViewById<TextView>(R.id.btnTrailer)
        val btnImdbS = cardView.findViewById<TextView>(R.id.btnImdb)
        linkButtonsS.visibility = View.VISIBLE
        btnTrailerS.visibility = View.GONE  // Sonarr doesn't have trailer IDs
        btnImdbS.visibility = if (show.imdbId != null) View.VISIBLE else View.GONE
        btnImdbS.setOnClickListener {
            val intent = android.content.Intent(android.content.Intent.ACTION_VIEW,
                android.net.Uri.parse("https://www.imdb.com/title/${show.imdbId}"))
            startActivity(intent)
        }

        show.posterUrl?.let { url ->
            Glide.with(this)
                .load(url)
                .centerCrop()
                .into(ivPoster)
        }

        return cardView
    }

    private fun setupShowSwipeGesture(cardView: CardView, show: Show) {
        var startX = 0f
        var startY = 0f
        var currentX = 0f
        var currentY = 0f
        val threshold = 200f

        val tvKeepLabel = cardView.findViewById<TextView>(R.id.tvKeepLabel)
        val tvBlockLabel = cardView.findViewById<TextView>(R.id.tvBlockLabel)

        cardView.setOnTouchListener { v, event ->
            when (event.action) {
                android.view.MotionEvent.ACTION_DOWN -> {
                    startX = event.rawX
                    startY = event.rawY
                    true
                }
                android.view.MotionEvent.ACTION_MOVE -> {
                    currentX = event.rawX - startX
                    currentY = event.rawY - startY

                    if (abs(currentX) > abs(currentY) && abs(currentX) > 10) {
                        v.translationX = currentX
                        v.rotation = currentX / 30f

                        if (currentX > 50) {
                            tvKeepLabel.visibility = View.VISIBLE
                            tvKeepLabel.text = "KEEP"
                            tvKeepLabel.alpha = minOf(abs(currentX) / threshold, 1f)
                            tvKeepLabel.setTextColor(resources.getColor(android.R.color.holo_green_light, theme))
                            tvBlockLabel.visibility = View.GONE
                        } else if (currentX < -50) {
                            tvBlockLabel.visibility = View.VISIBLE
                            tvBlockLabel.alpha = minOf(abs(currentX) / threshold, 1f)
                            tvKeepLabel.visibility = View.GONE
                        }
                        true
                    } else if (currentY > 50 && abs(currentY) > abs(currentX)) {
                        v.translationY = currentY * 0.5f
                        tvKeepLabel.visibility = View.VISIBLE
                        tvKeepLabel.text = "⭐ SUPER"
                        tvKeepLabel.alpha = minOf(abs(currentY) / threshold, 1f)
                        tvKeepLabel.setTextColor(resources.getColor(android.R.color.holo_orange_light, theme))
                        tvBlockLabel.visibility = View.GONE
                        true
                    } else if (currentY < -50 && abs(currentY) > abs(currentX)) {
                        v.translationY = currentY * 0.5f
                        tvBlockLabel.visibility = View.VISIBLE
                        tvBlockLabel.text = "SKIP"
                        tvBlockLabel.alpha = minOf(abs(currentY) / threshold, 1f)
                        tvBlockLabel.setTextColor(resources.getColor(android.R.color.holo_orange_light, theme))
                        tvKeepLabel.visibility = View.GONE
                        true
                    } else {
                        false
                    }
                }
                android.view.MotionEvent.ACTION_UP, android.view.MotionEvent.ACTION_CANCEL -> {
                    if (abs(currentX) > threshold && abs(currentX) > abs(currentY)) {
                        val goRight = currentX > 0
                        if (goRight) {
                            animateCardOut(true) {
                                api.keepShow(show.id) { ok, error -> reportActionFailure(ok, error) }
                                advanceCard()
                            }
                        } else {
                            blockShowWithUndo()
                        }
                    } else if (currentY > threshold && abs(currentY) > abs(currentX)) {
                        animateCardDown {
                            api.superKeepShow(show.id) { ok, error -> reportActionFailure(ok, error) }
                            advanceCard()
                        }
                    } else if (currentY < -threshold && abs(currentY) > abs(currentX)) {
                        animateCardUp {
                            api.skipShow(show.id) { ok, error -> reportActionFailure(ok, error) }
                            advanceCard()
                        }
                    } else {
                        v.animate().translationX(0f).translationY(0f).rotation(0f).setDuration(200).start()
                        tvKeepLabel.visibility = View.GONE
                        tvBlockLabel.visibility = View.GONE
                    }
                    currentX = 0f
                    currentY = 0f
                    true
                }
                else -> false
            }
        }
    }

    private fun animateCardDown(onEnd: () -> Unit) {
        val card = binding.cardContainer.getChildAt(0) ?: run { onEnd(); return }

        val animY = ObjectAnimator.ofFloat(card, "translationY", card.height.toFloat())
        val animA = ObjectAnimator.ofFloat(card, "alpha", 0f)

        AnimatorSet().apply {
            playTogether(animY, animA)
            duration = 300
            interpolator = AccelerateDecelerateInterpolator()
            addListener(object : AnimatorListenerAdapter() {
                override fun onAnimationEnd(animation: Animator) {
                    onEnd()
                }
            })
            start()
        }
    }

    private fun animateCardUp(onEnd: () -> Unit) {
        val card = binding.cardContainer.getChildAt(0) ?: run { onEnd(); return }

        val animY = ObjectAnimator.ofFloat(card, "translationY", -card.height.toFloat())
        val animA = ObjectAnimator.ofFloat(card, "alpha", 0f)

        AnimatorSet().apply {
            playTogether(animY, animA)
            duration = 300
            interpolator = AccelerateDecelerateInterpolator()
            addListener(object : AnimatorListenerAdapter() {
                override fun onAnimationEnd(animation: Animator) { onEnd() }
            })
            start()
        }
    }

    // ==================== DISCOVER METHODS ====================

    private fun loadDiscover() {
        if (isLoading) return
        isLoading = true
        discoverRequestId++  // Increment request ID
        val thisRequest = discoverRequestId
        binding.tvStats.visibility = View.GONE
        binding.tvStats.text = "Loading discover..."

        val prefs = getSharedPreferences("movieswipe", MODE_PRIVATE)
        selectedProviders = prefs.getString("selected_providers", "") ?: ""

        if (discoverType == "movies") {
            api.discoverMovies(page = discoverPage, limit = 20, providers = selectedProviders, sortBy = discoverSort) { response, error ->
                runOnUiThread {
                    // Skip if a newer request was made
                    if (thisRequest != discoverRequestId) return@runOnUiThread
                    isLoading = false
                    if (error != null) { binding.tvStats.text = "ERROR"; return@runOnUiThread }
                    if (response != null && response.movies.isNotEmpty()) {
                        discoverItems.clear()
                        discoverItems.addAll(response.movies)
                        currentIndex = 0
                        binding.tvStats.visibility = View.GONE
                        binding.tvStats.text = "Discover: page $discoverPage"
                        showCurrentCard()
                    } else {
                        binding.tvStats.text = "No more movies!"
                    }
                }
            }
        } else {
            api.discoverShows(page = discoverPage, limit = 20, providers = selectedProviders, sortBy = discoverSort) { response, error ->
                runOnUiThread {
                    // Skip if a newer request was made
                    if (thisRequest != discoverRequestId) return@runOnUiThread
                    isLoading = false
                    if (error != null) { binding.tvStats.text = "ERROR"; return@runOnUiThread }
                    if (response != null && response.shows.isNotEmpty()) {
                        discoverItems.clear()
                        discoverItems.addAll(response.shows)
                        currentIndex = 0
                        binding.tvStats.visibility = View.GONE
                        binding.tvStats.text = "Discover: page $discoverPage"
                        showCurrentCard()
                    } else {
                        binding.tvStats.text = "No more shows!"
                    }
                }
            }
        }
    }

    private fun createDiscoverCardView(item: DiscoverItem): CardView {
        val cardView = LayoutInflater.from(this).inflate(R.layout.card_movie, binding.cardContainer, false) as CardView

        // Show discover controls on card
        val discoverControls = cardView.findViewById<LinearLayout>(R.id.discoverControls)
        discoverControls?.visibility = View.VISIBLE
        
        val tvDiscoverToggle = cardView.findViewById<TextView>(R.id.tvDiscoverToggle)
        val tvSortToggle = cardView.findViewById<TextView>(R.id.tvSortToggle)
        
        // Set current labels
        tvDiscoverToggle.text = if (discoverType == "movies") "🎬 Movies" else "📺 Shows"
        tvSortToggle.text = when (discoverSort) {
            "popularity.desc" -> "🔥 Popular"
            "release_date.desc" -> "🆕 Newest"
            "vote_average.desc" -> "⭐ Top"
            else -> "🔥 Popular"
        }
        
        // Discover type toggle
        tvDiscoverToggle.setOnClickListener {
            discoverType = if (discoverType == "movies") "shows" else "movies"
            tvDiscoverToggle.text = if (discoverType == "movies") "🎬 Movies" else "📺 Shows"
            currentIndex = 0
            discoverPage = 1
            discoverItems.clear()
            binding.cardContainer.removeAllViews()
            loadDiscover()
        }
        
        // Sort toggle
        tvSortToggle.setOnClickListener {
            discoverSort = when (discoverSort) {
                "popularity.desc" -> "release_date.desc"
                "release_date.desc" -> "vote_average.desc"
                "vote_average.desc" -> "popularity.desc"
                else -> "popularity.desc"
            }
            tvSortToggle.text = when (discoverSort) {
                "popularity.desc" -> "🔥 Popular"
                "release_date.desc" -> "🆕 Newest"
                "vote_average.desc" -> "⭐ Top"
                else -> "🔥 Popular"
            }
            currentIndex = 0
            discoverPage = 1
            discoverItems.clear()
            binding.cardContainer.removeAllViews()
            loadDiscover()
        }

        val ivPoster = cardView.findViewById<ImageView>(R.id.ivPoster)
        val tvTitle = cardView.findViewById<TextView>(R.id.tvTitle)
        val tvYear = cardView.findViewById<TextView>(R.id.tvYear)
        val tvSize = cardView.findViewById<TextView>(R.id.tvSize)
        val tvRating = cardView.findViewById<TextView>(R.id.tvRating)
        val tvGenres = cardView.findViewById<TextView>(R.id.tvGenres)
        val tvCast = cardView.findViewById<TextView>(R.id.tvCast)
        val tvOverview = cardView.findViewById<TextView>(R.id.tvOverview)

        tvTitle.text = item.title
        tvYear.text = item.year ?: ""
        tvSize.text = if (discoverType == "movies") "🎬 Movie" else "📺 Show"
        tvRating.text = item.rating?.let { "⭐ ${String.format("%.1f", it)}"} ?: ""
        tvGenres.text = ""
        tvCast.text = item.cast?.joinToString(", ") ?: ""
        tvOverview.text = item.overview

        // TMDb link for discover items
        val linkButtonsD = cardView.findViewById<LinearLayout>(R.id.linkButtons)
        val btnTrailerD = cardView.findViewById<TextView>(R.id.btnTrailer)
        val btnImdbD = cardView.findViewById<TextView>(R.id.btnImdb)
        linkButtonsD.visibility = View.VISIBLE
        btnTrailerD.visibility = View.GONE
        btnImdbD.text = "🔗 TMDb"
        btnImdbD.setOnClickListener {
            val mediaType = if (discoverType == "movies") "movie" else "tv"
            val intent = android.content.Intent(android.content.Intent.ACTION_VIEW,
                android.net.Uri.parse("https://www.themoviedb.org/${mediaType}/${item.tmdbId}"))
            startActivity(intent)
        }

        item.posterUrl?.let { url ->
            Glide.with(this).load(url).centerCrop().into(ivPoster)
        }

        return cardView
    }

    private fun setupDiscoverSwipeGesture(cardView: CardView, item: DiscoverItem) {
        var startX = 0f
        var startY = 0f
        var currentX = 0f
        var currentY = 0f
        val threshold = 200f

        val tvKeepLabel = cardView.findViewById<TextView>(R.id.tvKeepLabel)
        val tvBlockLabel = cardView.findViewById<TextView>(R.id.tvBlockLabel)

        cardView.setOnTouchListener { v, event ->
            when (event.action) {
                android.view.MotionEvent.ACTION_DOWN -> {
                    startX = event.rawX; startY = event.rawY; true
                }
                android.view.MotionEvent.ACTION_MOVE -> {
                    currentX = event.rawX - startX; currentY = event.rawY - startY
                    if (abs(currentX) > abs(currentY) && abs(currentX) > 10) {
                        v.translationX = currentX; v.rotation = currentX / 30f
                        if (currentX > 50) {
                            tvKeepLabel.visibility = View.VISIBLE; tvKeepLabel.text = "ADD"
                            tvKeepLabel.alpha = minOf(abs(currentX) / threshold, 1f)
                            tvKeepLabel.setTextColor(resources.getColor(android.R.color.holo_green_light, theme))
                            tvBlockLabel.visibility = View.GONE
                        } else if (currentX < -50) {
                            tvBlockLabel.visibility = View.VISIBLE; tvBlockLabel.text = "HIDE"
                            tvBlockLabel.alpha = minOf(abs(currentX) / threshold, 1f)
                            tvKeepLabel.visibility = View.GONE
                        }
                        true
                    } else { false }
                }
                android.view.MotionEvent.ACTION_UP, android.view.MotionEvent.ACTION_CANCEL -> {
                    if (abs(currentX) > threshold && abs(currentX) > abs(currentY)) {
                        val goRight = currentX > 0
                        if (goRight) {
                            animateCardOut(true) {
                                if (discoverType == "movies") api.addMovieFromDiscover(item.tmdbId) { ok, error -> reportActionFailure(ok, error) }
                                else api.addShowFromDiscover(item.tmdbId) { ok, error -> reportActionFailure(ok, error) }
                                advanceCard()
                            }
                        } else {
                            dislikeDiscoverWithUndo()
                        }
                    } else {
                        v.animate().translationX(0f).translationY(0f).rotation(0f).setDuration(200).start()
                        tvKeepLabel.visibility = View.GONE; tvBlockLabel.visibility = View.GONE
                    }
                    currentX = 0f; currentY = 0f; true
                }
                else -> false
            }
        }
    }
}
