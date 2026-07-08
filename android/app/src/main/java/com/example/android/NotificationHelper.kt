package com.example.android

import android.app.*
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat

class NotificationHelper(private val context: Context) {

    private val channelId = "alert_channel"
    private val badgeChannelId = "badge_channel"

    init {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                channelId,
                "异常通知",
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                setShowBadge(false)   // 避免与 badge 通知重复计数
            }

            val badgeChannel = NotificationChannel(
                badgeChannelId,
                "未处理计数",
                NotificationManager.IMPORTANCE_LOW     // LOW 级别：状态栏显示但无声音，确保角标生效
            ).apply {
                setShowBadge(true)
                description = "用于桌面图标显示未处理异常数量"
            }

            val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            manager.createNotificationChannel(channel)
            manager.createNotificationChannel(badgeChannel)
        }
    }

    fun showNotification(title: String, content: String) {
        val builder = NotificationCompat.Builder(context, channelId)
            .setContentTitle(title)
            .setContentText(content)
            .setSmallIcon(R.drawable.ic_notification)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)

        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.notify(System.currentTimeMillis().toInt(), builder.build())
    }

    /**
     * 更新桌面图标角标数字（未处理异常数量）
     */
    fun updateBadgeCount(count: Int) {
        if (count <= 0) {
            // 取消角标通知
            val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            manager.cancel(9999)
            return
        }

        val intent = context.packageManager.getLaunchIntentForPackage(context.packageName)

        val pendingIntent = PendingIntent.getActivity(
            context,
            0,
            intent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )

        val builder = NotificationCompat.Builder(context, badgeChannelId)
            .setContentTitle("异常信息")
            .setContentText("有 $count 条未处理异常")
            .setSmallIcon(R.drawable.ic_notification)
            .setNumber(count)
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setCategory(NotificationCompat.CATEGORY_STATUS)

        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.notify(9999, builder.build())
    }
}