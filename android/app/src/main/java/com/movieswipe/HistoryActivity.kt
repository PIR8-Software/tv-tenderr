package com.movieswipe

import android.graphics.Color
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.ImageView
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.bumptech.glide.Glide
import com.movieswipe.databinding.ActivityHistoryBinding

class HistoryActivity : AppCompatActivity() {

    private lateinit var binding: ActivityHistoryBinding
    private lateinit var api: ApiClient
    private val allItems = mutableListOf<HistoryItem>()
    private var currentFilter = "all"
    private var searchQuery = ""
    private var historyMode = "movies"

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityHistoryBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val serverUrl = getSharedPreferences("movieswipe", MODE_PRIVATE)
            .getString("server_url", "http://localhost:8899") ?: "http://localhost:8899"
        api = ApiClient(serverUrl, storedApiToken(this))

        historyMode = intent.getStringExtra("mode") ?: "movies"

        binding.btnBack.setOnClickListener { finish() }

        binding.tvFilter.setOnClickListener {
            if (historyMode == "discover") return@setOnClickListener
            currentFilter = when (currentFilter) {
                "all" -> "keep"
                "keep" -> "super_keep"
                "super_keep" -> "block"
                "block" -> "clean"
                "clean" -> "all"
                else -> "all"
            }
            binding.tvFilter.text = currentFilter.replaceFirstChar { it.uppercase() }.replace("_", " ")
            refreshList()
        }

        binding.etSearch.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                searchQuery = s?.toString()?.trim()?.lowercase() ?: ""
                refreshList()
            }
        })

        binding.rvHistory.layoutManager = LinearLayoutManager(this)
        loadHistory()
    }

    override fun onResume() {
        super.onResume()
        loadHistory()
    }

    private fun loadHistory() {
        when (historyMode) {
            "movies" -> {
                api.getHistory { response, error ->
                    runOnUiThread {
                        if (error != null || response == null) return@runOnUiThread
                        allItems.clear()
                        allItems.addAll(response.history)
                        refreshList()
                    }
                }
            }
            "shows" -> {
                api.getShowHistory { response, error ->
                    runOnUiThread {
                        if (error != null || response == null) return@runOnUiThread
                        allItems.clear()
                        allItems.addAll(response.history)
                        refreshList()
                    }
                }
            }
            "discover" -> {
                api.getDiscoverHistory { response, error ->
                    runOnUiThread {
                        if (error != null || response == null) return@runOnUiThread
                        allItems.clear()
                        allItems.addAll(response.history)
                        refreshList()
                    }
                }
            }
        }
    }

    private fun applyHistoryResult(ok: Boolean, error: String?, item: HistoryItem) {
        runOnUiThread {
            if (ok) {
                allItems.removeAll { it.movieId == item.movieId }
                refreshList()
            } else {
                android.widget.Toast.makeText(this, error ?: "History action failed", android.widget.Toast.LENGTH_LONG).show()
            }
        }
    }

    private fun refreshList() {
        var filtered = if (currentFilter == "all" || historyMode == "discover") allItems.toList()
            else allItems.filter { it.action == currentFilter }

        if (searchQuery.isNotEmpty()) {
            filtered = filtered.filter {
                (it.title?.lowercase()?.contains(searchQuery) == true) ||
                (it.year?.toString()?.contains(searchQuery) == true)
            }
        }

        binding.rvHistory.adapter = HistoryAdapter(filtered,
            onUnkeep = { item ->
                when (historyMode) {
                    "movies" -> {
                        api.unkeepMovie(item.movieId) { ok, error -> applyHistoryResult(ok, error, item) }
                    }
                    "shows" -> {
                        api.postShowAction(item.movieId, "unkeep") { ok, error -> applyHistoryResult(ok, error, item) }
                    }
                    "discover" -> {
                        // "Added" items: remove from Radarr/Sonarr
                        if (item.type == "show") {
                            api.removeShowFromDiscover(item.movieId) { ok, error -> applyHistoryResult(ok, error, item) }
                        } else {
                            api.removeMovieFromDiscover(item.movieId) { ok, error -> applyHistoryResult(ok, error, item) }
                        }
                    }
                }
            },
            onUnblock = { item ->
                when (historyMode) {
                    "movies" -> {
                        api.unblockMovie(item.movieId) { ok, error -> applyHistoryResult(ok, error, item) }
                    }
                    "shows" -> {
                        api.postShowAction(item.movieId, "unblock") { ok, error -> applyHistoryResult(ok, error, item) }
                    }
                    "discover" -> {
                        // "Hidden" items: unhide (show in discover again)
                        api.unhideDiscover(item.movieId) { ok, error -> applyHistoryResult(ok, error, item) }
                    }
                }
            },
            onUnclean = { item ->
                if (historyMode == "shows") {
                    api.uncleanShow(item.movieId) { ok, error -> applyHistoryResult(ok, error, item) }
                }
            }
        )
    }
}

class HistoryAdapter(
    private val items: List<HistoryItem>,
    private val onUnkeep: (HistoryItem) -> Unit,
    private val onUnblock: (HistoryItem) -> Unit,
    private val onUnclean: (HistoryItem) -> Unit
) : RecyclerView.Adapter<HistoryAdapter.ViewHolder>() {

    class ViewHolder(view: View) : RecyclerView.ViewHolder(view) {
        val ivPoster: ImageView = view.findViewById(R.id.ivPoster)
        val tvTitle: TextView = view.findViewById(R.id.tvTitle)
        val tvYear: TextView = view.findViewById(R.id.tvYear)
        val tvAction: TextView = view.findViewById(R.id.tvAction)
        val btnUndo: Button = view.findViewById(R.id.btnUndo)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val view = LayoutInflater.from(parent.context).inflate(R.layout.item_history, parent, false)
        return ViewHolder(view)
    }

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        val item = items[position]
        holder.tvTitle.text = item.title ?: "Unknown #${item.movieId}"
        holder.tvYear.text = item.year?.toString() ?: ""

        when (item.action) {
            "keep" -> {
                holder.tvAction.text = "✓ KEPT (6mo)"
                holder.tvAction.setTextColor(Color.parseColor("#2ecc71"))
                holder.btnUndo.text = historyUndoLabel(item.action)
                holder.btnUndo.visibility = View.VISIBLE
                holder.btnUndo.setOnClickListener { onUnkeep(item) }
            }
            "super_keep" -> {
                holder.tvAction.text = "⭐ SUPER KEEP"
                holder.tvAction.setTextColor(Color.parseColor("#f1c40f"))
                holder.btnUndo.text = historyUndoLabel(item.action)
                holder.btnUndo.visibility = View.VISIBLE
                holder.btnUndo.setOnClickListener { onUnkeep(item) }
            }
            "block" -> {
                holder.tvAction.text = "✗ BLOCKED"
                holder.tvAction.setTextColor(Color.parseColor("#e74c3c"))
                holder.btnUndo.text = historyUndoLabel(item.action)
                holder.btnUndo.visibility = View.VISIBLE
                holder.btnUndo.setOnClickListener { onUnblock(item) }
            }
            "skip" -> {
                holder.tvAction.text = "→ SKIPPED"
                holder.tvAction.setTextColor(Color.parseColor("#f39c12"))
                holder.btnUndo.visibility = View.GONE
            }
            "clean" -> {
                holder.tvAction.text = "🧹 CLEANED"
                holder.tvAction.setTextColor(Color.parseColor("#3498db"))
                holder.btnUndo.text = historyUndoLabel(item.action)
                holder.btnUndo.visibility = View.VISIBLE
                holder.btnUndo.setOnClickListener { onUnclean(item) }
            }
            "added" -> {
                holder.tvAction.text = "⬇️ ADDED"
                holder.tvAction.setTextColor(Color.parseColor("#2ecc71"))
                holder.btnUndo.text = historyUndoLabel(item.action)
                holder.btnUndo.visibility = View.VISIBLE
                holder.btnUndo.setOnClickListener { onUnkeep(item) }
            }
            "hidden" -> {
                holder.tvAction.text = "✗ DISLIKED"
                holder.tvAction.setTextColor(Color.parseColor("#e74c3c"))
                holder.btnUndo.text = historyUndoLabel(item.action)
                holder.btnUndo.visibility = View.VISIBLE
                holder.btnUndo.setOnClickListener { onUnblock(item) }
            }
        }

        item.posterUrl?.let { url ->
            Glide.with(holder.itemView.context).load(url).centerCrop().into(holder.ivPoster)
        }
    }

    override fun getItemCount() = items.size
}
