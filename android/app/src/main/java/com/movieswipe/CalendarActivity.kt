package com.movieswipe

import android.graphics.Color
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.bumptech.glide.Glide

class CalendarActivity : AppCompatActivity() {

    private lateinit var api: ApiClient
    private var currentDays = 30

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_calendar)

        val serverUrl = getSharedPreferences("movieswipe", MODE_PRIVATE)
            .getString("server_url", "http://10.0.2.2:8899") ?: "http://10.0.2.2:8899"
        api = ApiClient(serverUrl, storedApiToken(this))

        findViewById<TextView>(R.id.btnCalendarBack).setOnClickListener { finish() }

        setupDaysChips()
        loadCalendar()
    }

    private fun setupDaysChips() {
        val daysOptions = listOf(7, 14, 30, 60, 90)
        val labels = listOf("7 days", "2 weeks", "1 month", "2 months", "3 months")
        val container = findViewById<LinearLayout>(R.id.daysChips)

        for ((idx, days) in daysOptions.withIndex()) {
            val chip = TextView(this)
            chip.text = labels[idx]
            chip.textSize = 12f
            chip.setPadding(24, 12, 24, 12)
            chip.setBackgroundResource(R.drawable.chip_bg)
            chip.setTextColor(Color.WHITE)
            chip.isSelected = days == currentDays
            val params = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            )
            params.setMargins(0, 0, 12, 0)
            chip.layoutParams = params
            chip.setOnClickListener {
                currentDays = days
                for (i in 0 until container.childCount) {
                    container.getChildAt(i).isSelected = false
                }
                chip.isSelected = true
                loadCalendar()
            }
            container.addView(chip)
        }
    }

    private fun loadCalendar() {
        api.getCalendar(currentDays) { response, error ->
            runOnUiThread {
                if (response != null && response.calendar.isNotEmpty()) {
                    val recyclerView = findViewById<RecyclerView>(R.id.calendarList)
                    recyclerView.layoutManager = LinearLayoutManager(this)
                    recyclerView.adapter = CalendarAdapter(response.calendar)
                }
            }
        }
    }

    inner class CalendarAdapter(private val items: List<CalendarItem>) :
        RecyclerView.Adapter<CalendarAdapter.ViewHolder>() {

        inner class ViewHolder(view: View) : RecyclerView.ViewHolder(view) {
            val ivPoster: ImageView = view.findViewById(R.id.ivCalPoster)
            val tvTitle: TextView = view.findViewById(R.id.tvCalTitle)
            val tvMeta: TextView = view.findViewById(R.id.tvCalMeta)
            val tvDate: TextView = view.findViewById(R.id.tvCalDate)
            val tvType: TextView = view.findViewById(R.id.tvCalType)
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
            val view = LayoutInflater.from(parent.context)
                .inflate(R.layout.item_calendar, parent, false)
            return ViewHolder(view)
        }

        override fun onBindViewHolder(holder: ViewHolder, position: Int) {
            val item = items[position]

            holder.tvTitle.text = item.title ?: "Unknown"

            if (item.type == "movie") {
                holder.tvMeta.text = buildString {
                    item.year?.let { append(it); append(" · ") }
                    append(if (item.hasFile) "✅ Downloaded" else if (item.monitored) "📡 Monitoring" else "⏸ Not monitored")
                }
                holder.tvType.text = "🎬"
                holder.tvType.setBackgroundResource(R.drawable.chip_bg)
            } else {
                holder.tvMeta.text = buildString {
                    append(item.episode ?: "")
                    item.episodeTitle?.let { append(" · $it") }
                    append(" · ")
                    append(if (item.hasFile) "✅ Downloaded" else if (item.monitored) "📡 Monitoring" else "⏸ Not monitored")
                }
                holder.tvType.text = "📺"
                holder.tvType.setBackgroundResource(R.drawable.chip_bg)
            }

            holder.tvDate.text = item.releaseDate ?: ""

            item.posterUrl?.let { url ->
                Glide.with(this@CalendarActivity)
                    .load(url)
                    .centerCrop()
                    .into(holder.ivPoster)
            }
        }

        override fun getItemCount() = items.size
    }
}
