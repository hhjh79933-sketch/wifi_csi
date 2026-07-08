package com.example.android

import android.graphics.Color
import android.os.Bundle
import android.view.View
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.EditText
import android.widget.Spinner
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity

class AlertDetailActivity : AppCompatActivity() {

    private lateinit var tvTitleRoom: TextView
    private lateinit var tvDetailState: TextView
    private lateinit var tvDetailMessage: TextView
    private lateinit var tvDetailRoom: TextView
    private lateinit var tvDetailTime: TextView
    private lateinit var tvDetailId: TextView
    private lateinit var spDetailState: Spinner
    private lateinit var etNote: EditText

    private var currentAlert: Alert? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_alert_detail)

        // 返回
        findViewById<TextView>(R.id.tvBack).setOnClickListener {
            finish()
        }

        tvTitleRoom = findViewById(R.id.tvTitleRoom)
        tvDetailState = findViewById(R.id.tvDetailState)
        tvDetailMessage = findViewById(R.id.tvDetailMessage)
        tvDetailRoom = findViewById(R.id.tvDetailRoom)
        tvDetailTime = findViewById(R.id.tvDetailTime)
        tvDetailId = findViewById(R.id.tvDetailId)
        spDetailState = findViewById(R.id.spDetailState)
        etNote = findViewById(R.id.etNote)

        // 接收数据
        currentAlert = if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.TIRAMISU) {
            intent.getSerializableExtra("alert", Alert::class.java)
        } else {
            @Suppress("DEPRECATION")
            intent.getSerializableExtra("alert") as? Alert
        }

        currentAlert?.let { alert ->
            tvTitleRoom.text = alert.room
            tvDetailMessage.text = alert.message
            tvDetailRoom.text = alert.room
            tvDetailTime.text = alert.time
            tvDetailId.text = "No.${alert.id}"
            etNote.setText(alert.note)

            setupSpinner(alert)
            updateBadge(alert.state)
        }

        // 保存按钮
        findViewById<View>(R.id.btnSave).setOnClickListener {
            val note = etNote.text.toString().trim()
            if (note.length < 15) {
                etNote.error = "备注不能少于15个字（当前${note.length}字）"
                return@setOnClickListener
            }
            val alert = currentAlert ?: return@setOnClickListener
            ApiService().updateNote(alert.id, note) { success, message ->
                runOnUiThread {
                    Toast.makeText(this, message, Toast.LENGTH_SHORT).show()
                }
            }
        }
    }

    private fun setupSpinner(alert: Alert) {
        val items = listOf("未处理", "误报", "已处理")

        val adapter = ArrayAdapter(this, android.R.layout.simple_spinner_item, items)
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
        spDetailState.adapter = adapter

        val index = when (alert.state) {
            0 -> 1
            1 -> 2
            else -> 0
        }
        // 延迟设置选中项，避免触发初始回调
        spDetailState.post {
            spDetailState.setSelection(index, false)
        }

        spDetailState.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>, view: View?, pos: Int, id: Long) {
                val newState = when (pos) {
                    0 -> null
                    1 -> 0
                    2 -> 1
                    else -> null
                }

                if (newState == alert.state) return

                ApiService().updateAlertState(alert.id, newState) { success ->
                    runOnUiThread {
                        if (success) {
                            alert.state = newState
                            updateBadge(newState)
                            setResult(RESULT_OK)   // 通知列表页刷新
                            Toast.makeText(this@AlertDetailActivity, "状态更新成功", Toast.LENGTH_SHORT).show()
                        } else {
                            spDetailState.setSelection(index, false)
                            Toast.makeText(this@AlertDetailActivity, "状态更新失败", Toast.LENGTH_SHORT).show()
                        }
                    }
                }
            }

            override fun onNothingSelected(parent: AdapterView<*>) {}
        }
    }

    private fun updateBadge(state: Int?) {
        when (state) {
            null -> {
                tvDetailState.text = "未处理"
                tvDetailState.setTextColor(Color.WHITE)
                tvDetailState.background.setTint(Color.parseColor("#E53935"))
            }
            0 -> {
                tvDetailState.text = "误报"
                tvDetailState.setTextColor(Color.WHITE)
                tvDetailState.background.setTint(Color.parseColor("#FF9800"))
            }
            1 -> {
                tvDetailState.text = "已处理"
                tvDetailState.setTextColor(Color.WHITE)
                tvDetailState.background.setTint(Color.parseColor("#4CAF50"))
            }
        }
    }
}
