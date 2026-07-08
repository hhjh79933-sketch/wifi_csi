package com.example.android

import android.graphics.Color
import android.os.Handler
import android.os.Looper
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.*
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.RecyclerView

class AlertAdapter(
    private var list: List<Alert>,
    private val onItemClick: ((Alert) -> Unit)? = null
) : RecyclerView.Adapter<AlertAdapter.ViewHolder>() {

    private val apiService = ApiService()
    class ViewHolder(view: View) : RecyclerView.ViewHolder(view) {
        val indicatorStrip: View = view.findViewById(R.id.indicatorStrip)
        val room: TextView = view.findViewById(R.id.tvRoom)
        val message: TextView = view.findViewById(R.id.tvMessage)
        val time: TextView = view.findViewById(R.id.tvTime)
        val tvState: TextView = view.findViewById(R.id.tvState)
        val spinner: Spinner = view.findViewById(R.id.spState)
    }

    override fun onCreateViewHolder(
        parent: ViewGroup,
        viewType: Int
    ): ViewHolder {

        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_alert, parent, false)

        return ViewHolder(view)
    }

    override fun getItemCount(): Int = list.size

    override fun onBindViewHolder(
        holder: ViewHolder,
        position: Int
    ) {

        val alert = list[position]

        holder.room.text = alert.room
        holder.message.text = alert.message
        holder.time.text = alert.time

        // 点击卡片 → 回调给 Fragment 处理
        holder.itemView.setOnClickListener {
            onItemClick?.invoke(alert)
        }

        val items = listOf(
            "未处理",
            "误报",
            "已处理"
        )

        val adapter = ArrayAdapter(
            holder.itemView.context,
            android.R.layout.simple_spinner_item,
            items
        )

        adapter.setDropDownViewResource(
            android.R.layout.simple_spinner_dropdown_item
        )

        holder.spinner.adapter = adapter

        val index =
            when (alert.state) {
                0 -> 1
                1 -> 2
                else -> 0
            }

        // 先设置状态徽章，再延迟设置 Spinner 选中项，避免首点失效
        when (alert.state) {

            null -> {
                holder.tvState.text = "未处理"
                holder.tvState.setTextColor(Color.WHITE)
                holder.tvState.background.setTint(Color.parseColor("#E53935"))
                holder.indicatorStrip.setBackgroundColor(Color.parseColor("#E53935"))
            }

            0 -> {
                holder.tvState.text = "误报"
                holder.tvState.setTextColor(Color.WHITE)
                holder.tvState.background.setTint(Color.parseColor("#FF9800"))
                holder.indicatorStrip.setBackgroundColor(Color.parseColor("#FF9800"))
            }

            1 -> {
                holder.tvState.text = "已处理"
                holder.tvState.setTextColor(Color.WHITE)
                holder.tvState.background.setTint(Color.parseColor("#4CAF50"))
                holder.indicatorStrip.setBackgroundColor(Color.parseColor("#4CAF50"))
            }
        }

        // 延迟设置选中项，避免初始化时触发监听器
        Handler(Looper.getMainLooper()).post {
            holder.spinner.setSelection(index, false)
        }

        holder.spinner.onItemSelectedListener =
            object : AdapterView.OnItemSelectedListener {

                override fun onItemSelected(
                    parent: AdapterView<*>,
                    view: View?,
                    pos: Int,
                    id: Long
                ) {
                    val newState = when (pos) {
                        0 -> null
                        1 -> 0
                        2 -> 1
                        else -> null
                    }

                    // 如果没有变化，不发送请求
                    if (newState == alert.state) {
                        return
                    }

                    apiService.updateAlertState(
                        alert.id,
                        newState
                    ) { success ->

                        holder.itemView.post {

                            if (success) {

                                alert.state = newState

                                when (newState) {

                                    null -> {
                                        holder.tvState.text = "未处理"
                                        holder.tvState.setTextColor(Color.WHITE)
                                        holder.tvState.background.setTint(Color.parseColor("#E53935"))
                                        holder.indicatorStrip.setBackgroundColor(Color.parseColor("#E53935"))
                                    }

                                    0 -> {
                                        holder.tvState.text = "误报"
                                        holder.tvState.setTextColor(Color.WHITE)
                                        holder.tvState.background.setTint(Color.parseColor("#FF9800"))
                                        holder.indicatorStrip.setBackgroundColor(Color.parseColor("#FF9800"))
                                    }

                                    1 -> {
                                        holder.tvState.text = "已处理"
                                        holder.tvState.setTextColor(Color.WHITE)
                                        holder.tvState.background.setTint(Color.parseColor("#4CAF50"))
                                        holder.indicatorStrip.setBackgroundColor(Color.parseColor("#4CAF50"))
                                    }
                                }

                                Toast.makeText(
                                    holder.itemView.context,
                                    "状态更新成功",
                                    Toast.LENGTH_SHORT
                                ).show()

                            } else {

                                Toast.makeText(
                                    holder.itemView.context,
                                    "状态更新失败",
                                    Toast.LENGTH_SHORT
                                ).show()

                                holder.spinner.setSelection(index, false)
                            }
                        }
                    }
                }

                override fun onNothingSelected(parent: AdapterView<*>) {
                }
            }
    }

    fun updateData(newList: List<Alert>) {
        val diff = DiffUtil.calculateDiff(object : DiffUtil.Callback() {
            override fun getOldListSize() = list.size
            override fun getNewListSize() = newList.size
            override fun areItemsTheSame(oldPos: Int, newPos: Int) =
                list[oldPos].id == newList[newPos].id
            override fun areContentsTheSame(oldPos: Int, newPos: Int) =
                list[oldPos].state == newList[newPos].state &&
                list[oldPos].note == newList[newPos].note &&
                list[oldPos].message == newList[newPos].message &&
                list[oldPos].time == newList[newPos].time &&
                list[oldPos].room == newList[newPos].room
        })
        list = newList
        diff.dispatchUpdatesTo(this)
    }
}