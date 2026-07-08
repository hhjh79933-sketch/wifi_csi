package com.example.android

import android.app.DatePickerDialog
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.View
import android.widget.LinearLayout
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.fragment.app.Fragment
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale

class AlertFragment : Fragment(R.layout.fragment_alert) {

    private lateinit var recyclerView: RecyclerView
    private lateinit var swipeRefresh: SwipeRefreshLayout
    private lateinit var layoutEmpty: LinearLayout
    private lateinit var tvStats: TextView
    private lateinit var cardStats: View
    private lateinit var btnDateFilter: TextView
    private lateinit var adapter: AlertAdapter

    // 日期筛选：null = 全部
    private var selectedDate: String? = null

    // 从详情页返回时立即刷新
    private val detailLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) {
        loadAlerts()
    }

    private lateinit var notifier: NotificationHelper

    private var isFirstLoad = true
    private var lastSize = 0

    private val handler = Handler(Looper.getMainLooper())

    private val api = ApiService()

    private var isLoading = false

    // 轮询任务
    private val pollingRunnable = object : Runnable {
        override fun run() {
            if (!isAdded) return
            loadAlerts()
            handler.postDelayed(this, 3000)
        }
    }

    /**
     * 立即拉取告警（供轮询和下拉刷新共用）
     */
    private fun loadAlerts() {
        if (isLoading) return
        isLoading = true

        val masterKey = MasterKey.Builder(requireContext())
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()

        val userSp = EncryptedSharedPreferences.create(
            requireContext(),
            "user_secure",
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
        )

        val username = userSp.getString("username", null)

        if (username == null) {
            isLoading = false
            adapter.updateData(emptyList())
            layoutEmpty.visibility = View.VISIBLE
            swipeRefresh.visibility = View.GONE
            swipeRefresh.isRefreshing = false
            return
        }

        api.getAlerts(username) { alerts ->

            // 排序
            val sorted = alerts.sortedWith(
                compareBy<Alert> { if (it.state == null) 0 else 1 }
                    .thenByDescending { it.id }
            )

            // 日期筛选
            val filtered = if (selectedDate != null) {
                sorted.filter { it.time.startsWith(selectedDate!!) }
            } else {
                sorted
            }

            activity?.runOnUiThread {
                isLoading = false
                if (!isAdded) return@runOnUiThread

                adapter.updateData(filtered)
                swipeRefresh.isRefreshing = false

                // 统计
                val unprocessed = sorted.count { it.state == null }
                val today = sorted.count {
                    it.time.startsWith(java.text.SimpleDateFormat("yyyy-MM-dd", java.util.Locale.getDefault()).format(java.util.Date()))
                }
                if (sorted.isNotEmpty()) {
                    cardStats.visibility = View.VISIBLE
                    if (selectedDate != null) {
                        tvStats.text = "$selectedDate ${filtered.size} 条 · 未处理 ${filtered.count { it.state == null }} 条"
                    } else {
                        tvStats.text = "今日 $today 条 · 未处理 $unprocessed 条"
                    }
                } else {
                    cardStats.visibility = View.GONE
                }

                // 空状态
                if (filtered.isEmpty()) {
                    layoutEmpty.visibility = View.VISIBLE
                    swipeRefresh.visibility = View.GONE
                } else {
                    layoutEmpty.visibility = View.GONE
                    swipeRefresh.visibility = View.VISIBLE
                }

                // 角标
                (activity as? MainActivity)?.updateUnprocessedBadge(unprocessed)

                if (isFirstLoad) {
                    lastSize = sorted.size
                    isFirstLoad = false
                } else {
                    if (sorted.size > lastSize) {
                        val newAlert = sorted.first()
                        notifier.showNotification(
                            "异常提醒",
                            "病房 ${newAlert.room} 出现 ${newAlert.message}"
                        )
                        (activity as? MainActivity)?.showAlertBanner(
                            newAlert.room,
                            newAlert.message
                        )
                        lastSize = sorted.size
                    }
                }
            }
        }
    }

    override fun onViewCreated(
        view: View,
        savedInstanceState: Bundle?
    ) {

        super.onViewCreated(view, savedInstanceState)

        recyclerView = view.findViewById(R.id.recyclerView)
        swipeRefresh = view.findViewById(R.id.swipeRefresh)
        layoutEmpty = view.findViewById(R.id.layoutEmpty)
        tvStats = view.findViewById(R.id.tvStats)
        cardStats = view.findViewById(R.id.cardStats)
        btnDateFilter = view.findViewById(R.id.btnDateFilter)

        notifier = NotificationHelper(requireContext())

        adapter = AlertAdapter(emptyList()) { alert ->
            val intent = Intent(requireContext(), AlertDetailActivity::class.java)
            intent.putExtra("alert", alert)
            detailLauncher.launch(intent)
        }

        recyclerView.layoutManager =
            LinearLayoutManager(requireContext())

        recyclerView.adapter = adapter

        // 下拉刷新：立即拉取一次
        swipeRefresh.setOnRefreshListener {
            loadAlerts()
        }

        // 日期筛选
        btnDateFilter.setOnClickListener {
            val cal = Calendar.getInstance()
            // 有已选日期则预选中，否则默认今天
            selectedDate?.split("-")?.takeIf { it.size == 3 }?.let {
                cal.set(it[0].toInt(), it[1].toInt() - 1, it[2].toInt())
            }
            DatePickerDialog(
                requireContext(),
                { _, year, month, day ->
                    selectedDate = String.format("%04d-%02d-%02d", year, month + 1, day)
                    btnDateFilter.text = "📅"
                    loadAlerts()
                },
                cal.get(Calendar.YEAR),
                cal.get(Calendar.MONTH),
                cal.get(Calendar.DAY_OF_MONTH)
            ).show()
        }

        // 长按清除筛选
        btnDateFilter.setOnLongClickListener {
            selectedDate = null
            btnDateFilter.text = "📅"
            loadAlerts()
            true
        }
    }

    override fun onResume() {

        super.onResume()

        handler.post(pollingRunnable)
    }

    override fun onPause() {

        super.onPause()

        // 停止轮询
        handler.removeCallbacks(pollingRunnable)
    }
}